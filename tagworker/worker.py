import os
import time
import threading
import uuid
import traceback

import tldextract

from collections import defaultdict
from datetime import timedelta
from pytimeparse2 import parse

from .config import GlobalConfig
from .logger import logger
from .qbit import qBit
from .files import move_to_dir, is_file, build_inode_map, file_has_outer_links, translate_path, remove_empty_dirs

METHOD_API = 0
METHOD_DICT = 1

class worker:
    instances = []
    reacted = {}

    new_torrents = False

    def __init__(self, name, config, trackerissue_method = METHOD_API):
        self.id = uuid.uuid4()
        self.client = qBit(config.url, config.user, config.password)
        self.config = config
        self.name = name or tldextract.extract(config['url']).domain
        self.commands = getattr(config, 'commands', None)
        self.folders = getattr(config, 'folders', None)
        self.translation_table = getattr(config, 'translation_table', None)
        self.share_limits = getattr(config, 'share_limits', None)
        self.dryrun = getattr(config, 'dryrun', True)
        self.local_client = getattr(config, 'local_instance', False)
        self.trackerissue_method = trackerissue_method

        self.changes_dict = {}
        self._full_update_time = 0

        self.stop_event = threading.Event()
        self.tag_idle = threading.Event()
        self.tag_trigger = threading.Event()
        self.disk_idle = threading.Event()
        # si tags espera por el disco y el disco espera por tags... malo. iniciamos asi para iniciar por los tags (es quien hace sync)
        self.tag_idle.clear()
        self.disk_idle.set()

        self.tag_thread = self.disk_thread = None

        self.__class__.reacted[self] = False
        self.__class__.instances.append(self)

    @classmethod
    def get_instances(self):
        return self.instances

    @property
    def is_running(self):
        return bool(self.tag_thread or self.disk_thread)

    def run(self):
        try:
            self.client.login()
            logger.info(f"{self.name:<10} - logged in")
        except Exception as e:
            logger.error(f"{self.name:<10} - unable to log in. client disabled. {e}")
            return

        self.tag_thread = threading.Thread(target=self.task_tag)
        self.tag_thread.start()
        self.disk_thread = threading.Thread(target=self.task_disk)
        self.disk_thread.start()

    def stop(self):
        self.stop_event.set()
        self.tag_trigger.set()
        self.client.logout()
        if self.tag_thread: self.tag_thread.join()
        if self.disk_thread: self.disk_thread.join()
        self.tag_thread = self.disk_thread = None

    def torrents_changed(self, prop = None):
        # obtengo la informacion de los cambios de los torrents
        changed_t = self.client.sync_data.get('torrents', {})
        # ahora filtro los que no han tenido cambios que nos importen
        watched_props = [prop] if isinstance(prop, str) else prop
        all_torrents = self.client.torrents
        return {th: all_torrents[th] for th, tv in changed_t.items() if not watched_props or (watched_props & tv.keys())}

    def task_tag(self):
        commands = self.commands
        sl_torrent_queue = set()

        while not self.stop_event.is_set():
            wait_for_event("disk_done", self.disk_idle, self.name)
            self.tag_idle.clear()

            prev_torrents = set(self.client.torrents.keys())

            request_fullsync = time.time() - self._full_update_time > parse(GlobalConfig.get('app.fullsync_interval'))
            self.client.sync(request_fullsync)
            if request_fullsync:
                logger.info("%-10s - SYNCING WITH FULL DATA", self.name)
                self._full_update_time = time.time()
            #logger.debug(f"{self.name:<10} - --> {len(self.client.sync_data.get('torrents'))} changed")

            curr_torrents = set(self.client.torrents.keys())
            if curr_torrents != prev_torrents:
                logger.info(f"{self.name:<10} - torrentlist changed. broadcasting need to check dupes")
                # podria estar ya a true y con alguna instancia ya reaccionada. estas se lo podrian perder
                __class__.reacted = {key: False for key in __class__.reacted}

            tags_changed = False

            if GlobalConfig.get('app.dupes.enabled', False) and not __class__.reacted[self]:
                tags_changed |= self.tag_dupes()
                __class__.reacted[self] = True

            tag_funcs = {
                'tag_trackers': self.tag_trackers,
                'tag_HR': self.tag_HR,
                'scan_no_tmm': self.tag_TMM,
                'tag_issues': self.tag_issues,
                'tag_rename': self.tag_rename,
                'tag_lowseeds': self.tag_lowseeds,
                'tag_HUNO': self.tag_HUNO,
            }

            tags_changed = False
            for key, func in tag_funcs.items():
                if commands.get(key, False):
                    changes = func()
                    if changes: logger.debug(f"{self.name:<10} - {key} made changes.")
                    tags_changed |= changes

            if GlobalConfig.get('app.dupes.enabled', False) and not worker.reacted[self]:
                tags_changed |= self.tag_dupes()
                worker.reacted[self] = True

            tags_changed |= self.clean_noHL()

            sl_torrent_queue |= set(self.torrents_changed({'category', 'max_seeding_time', 'up_limit', 'tags'}).keys())

            if not tags_changed:
                # cuando los tags están en orden es cuando ajustamos SL
                if commands.get('share_limits', False): self.tag_SL(sl_torrent_queue)
                sl_torrent_queue.clear()
                # logger.debug(f"{self.name:<10} - sleeping {parse(TagWorker.appconfig.tagging_schedule_interval)}s...")
                self.tag_idle.set()
                self.tag_trigger.wait(timeout=parse(GlobalConfig.get('app.tagging_schedule_interval')))
                self.tag_trigger.clear()
            else:
                logger.debug(f"{self.name:<10} - changes have been made. looping...")
                self.stop_event.wait(2) # delay para que qbit aplique cambios. no uso tag_trigger pq no quiero que disk_task lo arranque. es un delay interrumpible, sin mas

    def task_disk(self):
        if not self.local_client:
            self.disk_idle.set()
            return

        commands = self.commands
        dry_run = self.dryrun
        while not self.stop_event.is_set():
            tagged = False
            try:
                wait_for_event("tag_done", self.tag_idle, self.name)
                self.disk_idle.clear()

                logger.info(f"{self.name:<10} - disk task started")

                if commands.get('tag_noHL'):
                    # logger.info(f"{self.name:<10} - checking hardlinks")
                    tagged = self.disk_noHL()
                if commands.get('clean_orphaned'):
                    # logger.info(f"{self.name:<10} - moving orphan files")
                    self.disk_orphans(dry_run)

                if commands.get('prune_orphaned'):
                    # logger.info(f"{self.name:<10} - pruning old orphans")
                    self.disk_prune_old(dry_run)

                if commands.get('delete_empty_dirs'):
                    remove_empty_dirs(self.folders.get('root_path'), dry_run, self.name)

            except Exception as e:
                logger.error(f"Error: {e}\n{traceback.format_exc()}")

            logger.info(f"{self.name:<10} - disk task done")
            self.disk_idle.set()
            if tagged:
                logger.debug(f"{self.name:<10} - triggering tag task")
                self.tag_trigger.set()
            self.stop_event.wait(timeout=parse(GlobalConfig.get("app.disktasks_schedule_interval")))

    def disk_orphans(self, dry_run = True):
        root_path = self.folders.get('root_path')
        orphan_path = self.folders.get('orphaned_path')

        # Recorre el directorio de descargas, excluyendo el de huerfanos
        hd_files = set()
        for root, dirs, files in os.walk(root_path):
            if root_path.startswith(orphan_path):
                dirs[:] = []
            else:
                dirs[:] = [d for d in dirs if not os.path.join(root, d).startswith(orphan_path)]

            for file in files:
                ruta_archivo = os.path.join(root, file)
                hd_files.add(ruta_archivo)

        # Forma el set con todos los archivos de todos los torrents
        referenced_files = set()
        torrents = self.client.torrents
        for thash, torrent in torrents.items():
            translated = translate_path(torrent.content_path, self.translation_table)
            if os.path.isfile(translated):
                files = {translated}
            elif os.path.isdir(translated):
                files = self.client.torrent_files(thash)
                files = {translate_path(file, self.translation_table) for file in files}
            else: # no existe el translated en el disco => errored/missing files torrent o descarga incompleta
                # TODO: torrent.state checks, error torrent tagging... ?
                logger.warning(f"Missing file: {torrent.name} - {translated}")
            if referenced_files & files:
                logger.warning(f"{self.name:<10} - Tracker-dupe? {torrent.name} ({tldextract.extract(torrent.tracker).domain}) files belong to multiple torrents")
            referenced_files.update(files)

        # Calcula los archivos huérfanos
        orphaned_files = hd_files - referenced_files
        if not len(orphaned_files):
            return

        # TODO
        # if len(orphaned_files) > 10:
        #     return
        logger.info(f'%-10s - {len(orphaned_files)} orphan files moved to {orphan_path}', self.name)
        for file in sorted(orphaned_files):
            if not dry_run:
                move_to_dir(root_path, orphan_path, file)
                logger.info(f"%-10s - moved {file} to {orphan_path}", self.name)
            else:
                logger.info(f"%-10s - *** DRY-RUN *** moved {file} to {orphan_path}", self.name)
        # remove_empty_dirs(root_path, url)

    def disk_prune_old(self, dry_run = True):
        path = self.folders.get('orphaned_path')
        expire_time = parse(GlobalConfig.get("app.prune_orphaned_time"))

        time_limit = time.time() - expire_time
        files_to_delete = set()

        for root, _, files in os.walk(path):
            for filename in files:
                fullpath = os.path.join(root, filename)
                mod_time = os.path.getmtime(fullpath)
                if mod_time < time_limit:
                    files_to_delete.add(fullpath)
        if files_to_delete:
            logger.info(f'%-10s - recycling {len(files_to_delete)} old orphans.', self.name)
            try:
                for fullpath in files_to_delete:
                    if not dry_run:
                        os.remove(fullpath)
                        logger.info(f"%-10s - Deleted {os.path.basename(fullpath)}", self.name)
                    else:
                        logger.info(f"%-10s - *** DRY-RUN *** deleted {os.path.basename(fullpath)}", self.name)
            except Exception as e:
                logger.warning(f'%-10s - Error trying to delete file {fullpath}: {e}', self.name)


        # remove_empty_dirs(path, url)
        # remove_empty_dirs(self.folders.get('root_path'), url)

    def disk_noHL(self):
        # creamos una lista con todos los inodos dentro del root_path y cuantas veces aparecen
        # posteriormente miramos los torrents uno a uno
        # si tiene HL fuera, el fichero deberia tener una cantidad de links superior a los que hemos encontrado
        #
        # en caso de multifile miraremos fichero a fichero sus contenidos hasta encontrar alguno que si tenga HL fuera
        def torrent_has_HL(torrent, inode_map, translation_table):
            realfile = translate_path(torrent.content_path, translation_table)
            if is_file(realfile):
                return file_has_outer_links(realfile, inode_map)
            # FIXME iterar contenidos del content_path. si hay algun HL lo damos por bueno
            for root, _, files in os.walk(translate_path(torrent.content_path, translation_table)):
                for file in files:
                    realfile = translate_path(file, translation_table)
                    fullpath = os.path.join(root, realfile)
                    if file_has_outer_links(fullpath, inode_map):
                        return True
            return False

        root_path = self.folders.get('root_path')
        translation_table = self.translation_table
        noHL_tag = GlobalConfig.get("app.noHL.tag")
        noHL_cats = GlobalConfig.get("app.noHL.categories")

        torrents = self.client.torrents
        if not torrents:
            return False
        inode_map = build_inode_map(root_path)
        noHLs, addtag, deltag = set(), set(), set()
        for thash, torrent in torrents.items():
            if torrent.category not in noHL_cats:
                continue

            tagged = noHL_tag in torrent.tags.split(", ")

            if not torrent_has_HL(torrent, inode_map, translation_table):
                noHLs.add(thash)
                if not tagged:
                    logger.info(f"{self.name:<10} - new noHL: {torrent.name}")
                    addtag.add(thash)
            elif tagged:
                logger.info(f"{self.name:<10} - {torrent.name} has links now.")
                deltag.add(thash)

        if addtag: self.client.add_tags(addtag, noHL_tag)
        if deltag: self.client.remove_tags(deltag, noHL_tag)

        logger.info(f"{self.name:<10} - {len(noHLs)} noHL. New {len(addtag)} - Untagged {len(deltag)}")
        return bool(addtag or deltag)

    def clean_noHL(self):
        """
        Si la instancia no es local no hace nada -> no limpia pq podria haber otro gestor
        Elimina los tags de noHL cuando:
         - un torrent pertenece a una categoria fuera del scan
         - noHL está deshabilitado
        """
        if not self.local_client:
            return False
        noHL_tag = GlobalConfig.get("app.noHL.tag")
        noHL_cats = GlobalConfig.get("app.noHL.categories")
        torrents = self.torrents_changed({'category', 'tags'})
        torrents = {th: tval for th, tval in torrents.items() if noHL_tag in tval['tags'].split(", ")} # filter torrents by noHL tag
        if not self.commands.get('tag_noHL'):
            hashes = torrents.keys()
            if hashes: logger.info(f"{self.name:<10} - Untagged {noHL_tag} {len(torrents)} torrents: tag_noHL command disabled")
        else:
            hashes = set()
            for thash, torrent in torrents.items():
                if torrent.get('category') not in noHL_cats:
                    logger.info(f"{self.name:<10} - Untagged {noHL_tag} {torrent.get('name')}: disabled category")
                    hashes.add(thash)
        if hashes:
            self.client.remove_tags(hashes, noHL_tag)
        return bool(hashes)

    def tag_lowseeds(self):
        torrents = self.torrents_changed({'num_seeds', 'tags', 'tracker', 'state'})
        if not torrents:
            return False

        addtag = set()
        deltag = set()
        tag = GlobalConfig.get("app.lowseeds.tag")
        min_seeds = GlobalConfig.get("app.lowseeds.min_seeds")
        for thash, torrent in torrents.items():
            tags = torrent.tags.split(', ')
            seeds = torrent.get('num_complete')
            if torrent.get('state','') in ['pausedUP','pausedDL', 'error', 'unknown']: # filtramos solos los que estan normal XD
                continue
            if seeds < min_seeds and isinstance(seeds, int):
                if tag not in tags:
                    addtag.add(thash)
            elif tag in tags:
                deltag.add(thash)

        if addtag:
            self.client.add_tags(addtag, tag)
        if deltag:
            self.client.remove_tags(deltag, tag)
        return bool(addtag or deltag)

    def tag_dupes(self):
        dupetag = GlobalConfig.get("app.dupes.tag")

        torrents = set()
        multiple_instances = False
        for uid, tset in qBit.all_torrents_iterator():
            if uid == self.client.id: continue # my torrents are not dupes!
            torrents.update(tset.keys())
            multiple_instances = True
        if not multiple_instances:
            logger.warning(f"{self.name:<10} - no other clients. skipping dupe tagging")
            return False

        my_torrents = self.client.torrents
        my_hashes = set(my_torrents.keys())
        dupes = torrents & my_hashes

        addtag = set()
        deltag = set()
        for thash, tval in my_torrents.items():
            tags = my_torrents[thash]['tags'].split(", ")
            if dupetag in tags:
                if thash not in dupes:
                    logger.debug(f"{self.name:<10} - {tval['name']} is a NOT dupe but it's tagged")
                    deltag.add(thash)
            elif thash in dupes:
                    logger.debug(f"{self.name:<10} - {tval['name']} is a dupe")
                    addtag.add(thash)

        if addtag: self.client.add_tags(addtag, dupetag) # taguea dupes
        if deltag: self.client.remove_tags(deltag, dupetag)

        logger.info(f"{self.name:<10} - Found {len(dupes)} dupes across all clients. Tagged {len(addtag)} - Untagged {len(deltag)}")

        return bool(addtag or deltag)

    def tag_issues(self):
        torrents = self.torrents_changed({'tracker', 'state', 'tags'})

        if not torrents:
            return False

        errored, unerrored = set(), set()
        errortag = GlobalConfig.get("app.issue.tag")
        for thash, torrent in torrents.items():
            ttags = torrent.tags.split(", ")
            if torrent.get('state') in ['pausedUP','pausedDL', 'error', 'unknown']:
                if errortag in ttags:
                    unerrored.add(thash)
                continue
            if self.trackerissue_method == METHOD_API:
                response = self.client.get_trackers(thash)
                working = False
                errormsg = ""
                for tracker in response:
                    if tracker.get('status') not in {0,4}:
                        working = True
                        break
                    else: errormsg = tracker.get('msg')
            else:
                errormsg = ''
                working = torrent.get('tracker')
            if not working:
                if errortag not in ttags:
                    errored.add(thash)
                logger.debug(f"{self.name:<10} - errored {tldextract.extract(torrent['tracker']).domain}: {torrent['name']} {'(' + errormsg + ')' if errormsg else ''}")
            elif errortag in ttags:
                logger.debug(f"{self.name:<10} - fixed {tldextract.extract(torrent['tracker']).domain}: {torrent['name']} ")
                unerrored.add(thash)

        if errored:
            self.client.add_tags(errored, errortag)
            logger.info(f"{self.name:<10} - {len(errored)} torrents with tracker issues")

        if unerrored:
            self.client.remove_tags(unerrored, errortag)
            logger.info(f"{self.name:<10} - {len(unerrored)} torrents fixed")

        return bool(errored or unerrored)

    def tag_HR(self):
        torrents = self.torrents_changed({'state', 'seeding_time', 'ratio', 'progress', 'tags'}) # a bit spammy
        client = self.client

        if not torrents:
            return False

        tracker_rules = GlobalConfig.get("tracker_details")
        hr_tag = GlobalConfig.get("app.HR.tag")
        exclude_xseed = GlobalConfig.get("app.HR.exclude_xseed")
        autostart_hr = GlobalConfig.get("app.HR.autostart")
        extra_time = GlobalConfig.get("app.HR.extra_seed_time")
        extra_ratio = GlobalConfig.get("app.HR.extra_ratio")

        unsatisfied = set()
        satisfied = set()
        autostart = set()

        for thash, torrent in torrents.items():
            seeding_time = torrent['seeding_time']
            torrent_ratio = torrent['ratio']
            torrent_tags = torrent.tags.split(", ")

            for key, rules in tracker_rules.items():
                if any(word in torrent['tracker'] for word in key.split("|")):
                    hr = getattr(rules, 'HR', None)
                    # satisfied
                    if (
                        not hr
                        or (seeding_time > parse(hr.time) + parse(extra_time))
                        or (getattr(hr,'ratio', None) and torrent_ratio > hr.ratio + extra_ratio)
                        or (exclude_xseed and torrent['downloaded'] == 0)
                        or (getattr(hr, 'percent', None) and (torrent['downloaded'] < (hr.percent/100) * torrent['size']))
                        ):
                        if hr_tag in torrent_tags:
                            satisfied.add(thash)
                    # H&R
                    else:
                        if hr_tag not in torrent_tags:
                            unsatisfied.add(thash)
                        if torrent['state'] in {'pausedUP', 'error'}:
                            autostart.add(thash)
                    break

        if unsatisfied:
            logger.info(f'%-10s - {len(unsatisfied)} unsatisfied', self.name)
            client.add_tags(unsatisfied, hr_tag)

        if satisfied:
            logger.info(f'%-10s - {len(satisfied)} now satisfied', self.name)
            client.remove_tags(satisfied, hr_tag)

        if autostart_hr and autostart:
            # client.force_start(autostart)
            logger.info(f'%-10s - resuming {len(autostart)} torrents', self.name)
            client.resume_torrents(autostart)

        return bool(unsatisfied or satisfied or (autostart_hr and autostart))

    def tag_HUNO(self):
        def tag(name):
            return GlobalConfig.get("app.huno_tag_prefix") + name
        torrents = self.torrents_changed({'seeding_time', 'tags'})
        client = self.client

        if not torrents:
            return False
        # logger.info(f'%s - HUNO: {len(torrents)} torrents', self.name)

        HUNO_TYPES = {
            "Legend": parse("5y"),
            "Champion": parse("1y"),
            "Knight": parse("6 months"),
            "Squire": parse("10d"),
            "Vanguard": parse("1d"),
        }

        tags_to_add = defaultdict(set)
        tags_to_remove = defaultdict(set)
        for thash, torrent in torrents.items():
            new_rank = None
            seeding_time = torrent['seeding_time']
            if 'hawke.uno' not in torrent['tracker'] or seeding_time < 86400: # 1d
                continue
            existing_tags = torrent['tags'].split(", ")

            # averiguo el adecuado
            for rank, min_time in HUNO_TYPES.items():
                if seeding_time >= min_time:
                    new_rank = rank
                    break

            # elimino los que no corresponden
            for rank, _ in HUNO_TYPES.items():
                if rank != new_rank and tag(rank) in existing_tags:
                    tags_to_remove[rank].add(thash)

            # averiguo si necesita el tag correcto o ya lo tiene
            if new_rank and tag(new_rank) not in existing_tags:
                tags_to_add[new_rank].add(thash)


        for rank, thashes in tags_to_add.items():
            logger.debug(f"{self.name:<10} - added {tag(rank)} tag to {len(thashes)} torrents")
            client.add_tags(thashes, tag(rank))

        for rank, thashes in tags_to_remove.items():
            logger.debug(f"{self.name:<10} - fixing {len(thashes)} {tag(rank)} tags")
            client.remove_tags(thashes, tag(rank))

        return bool(tags_to_add or tags_to_remove)

    def tag_TMM(self):
        torrents = self.torrents_changed({'auto_tmm', 'tags', 'category'})
        client = self.client
        config = GlobalConfig.get("app.noTMM")

        if not torrents:
            return False

        logger.info(f'%-10s - checking {len(torrents)} torrents autoTMM', self.name)

        tag = config.tag
        ignoredtags = getattr(config, 'ignored_tags', {})
        ignoredcats = getattr(config, 'ignored_categories', {})
        tag_add = set()
        tag_remove = set()
        for thash, tval in torrents.items():
            ttags = set(tval['tags'].split(', '))
            if tval['auto_tmm'] or (ignoredtags and ttags & ignoredtags) or (ignoredcats and tval['category'] in ignoredcats):
                # no deberia tenerlo
                if tag in ttags:
                    tag_remove.add(thash)
                continue
            # si deberia tenerlo
            tag_add.add(thash)

        if tag_add:
            # si activamos el tmm ya no hace falta taguearlo
            if config.auto_enable:
                client.enable_tmm(tag_add)
            else:
                client.add_tags(tag_add, tag)
        if tag_remove:
            client.remove_tags(tag_remove, tag)

        return bool(tag_add or tag_remove)

    def tag_rename(self):
        client = self.client
        tags_to_rename = GlobalConfig.get("app.tag_renamer")
        # obtengo la informacion de los cambios de los torrents
        changed_t = client.sync_data.get('tags', {}) & tags_to_rename.keys()

        if not changed_t:
            # logger.debug(f'%-10s - no tags to rename', self.name)
            return False

        logger.info(f'%-10s - {changed_t} must be renamed.', self.name)

        for old_tag, new_tag in tags_to_rename.items():
            if old_tag not in changed_t:
                continue
            hashes = {th for th, tv in client.torrents.items() if old_tag in tv.tags.split(", ")}
            client.add_tags(hashes, new_tag)

        self.client.delete_tags(tags_to_rename.keys()) # FIXME
        return True

    def tag_trackers(self):
        torrents = self.torrents_changed({'tracker', 'tags'})
        client = self.client
        tracker_details = GlobalConfig.get("tracker_details")

        if not torrents:
            return False

        try:
            default_tag = tracker_details.default.tag
        except KeyError:
            logger.warning(f"{self.name:<10} - tracker_details['default']['tag'] no está definido")
            default_tag = None

        addtag = defaultdict(set)
        deltag = defaultdict(set)

        for thash, torrent in torrents.items():
            torrent_tracker = torrent.get('tracker')
            if not torrent_tracker: continue
            good_tags, bad_tags = set(), set()
            torrent_tags = set(torrent.tags.split(", "))

            torrent_classified = False
            for expr, value in tracker_details.items():
                if expr == 'default': continue
                tracker_tags = set(value.get('tag', '').split(", "))
                words = {word.strip() for word in expr.split("|")}
                if any(word in torrent_tracker for word in words):
                    torrent_classified = True
                    # es un poco tonteria el |=. un torrent solo deberia matchear con una definicion
                    # pero... tampoco causaria problemas si lo hiciese con varias
                    good_tags |= tracker_tags
                    missing_tags = tracker_tags - torrent_tags
                    for tag in missing_tags:
                        addtag[tag].add(thash)
                    # era default y tenemos que quitarle el tag pq ya no lo es
                    if default_tag and default_tag in torrent_tags:
                        deltag[default_tag].add(thash)
                    # no break para poder eliminar tags de otras definiciones
                else:
                    bad_tags.update(tracker_tags & torrent_tags)
            # si llegamos a este punto sin tracker_tags, es que no coincide con ninguna descripcion de tracker -> deberia ser el default
            # aun asi, lo hacemos con torrent_classified por legibilidad
            if not torrent_classified and default_tag and default_tag not in torrent_tags:
                addtag[default_tag].add(thash)
            bad_tags -= good_tags
            for tag in bad_tags:
                deltag[tag].add(thash)

        for value, hashes in addtag.items():
            logger.info(f"{self.name:<10} - tagging {len(hashes)} torrents {value}")
            client.add_tags(hashes, value)

        for value, hashes in deltag.items():
            logger.info(f"{self.name:<10} - untagging {len(hashes)} torrents {value}")
            client.remove_tags(hashes, value)

        return bool(addtag or deltag)

    def tag_SL(self, torrentset):
        if not torrentset: return
        client = self.client

        logger.info(f"{self.name:<10} - setting {len(torrentset)} sharelimits")

        profiles = self.share_limits
        tagprefix = GlobalConfig.get("app.share_limits_tag_prefix")
        profiles_dict = dict()
        tagdict = dict()

        # lo inicializo con todos los nombres para que hayan items o no, se recorra para tag Y UNTAG
        for profile_name, profile_config in profiles.items():
            tagname = profile_config.get('custom_tag', tagprefix + profile_name)
            profiles_dict[profile_name] = set()
            tagdict[tagname] = set()

        torrents = {thash : self.client.torrents.get(thash) for thash in torrentset}

        for thash, torrent in torrents.items():
            if not torrent:
                logger.warning(f"{self.name:<10} - skipping hash {thash}. ")
                continue
            tags = torrent.tags.split(", ")
            # find matching profile
            for profile_name, profile_config in profiles.items():
                if (
                    ('category' in profile_config and not any(cat == torrent.category for cat in profile_config['category']))
                    or ('include_all_tags' in profile_config and not all(tag in tags for tag in profile_config['include_all_tags']))
                    or ('include_any_tags' in profile_config and not any(tag in tags for tag in profile_config['include_any_tags']))
                    or ('exclude_all_tags' in profile_config and all(tag in tags for tag in profile_config['exclude_all_tags']))
                    or ('exclude_any_tags' in profile_config and any(tag in tags for tag in profile_config['exclude_any_tags']))
                ):
                    continue

                tagname = profile_config.get('custom_tag', tagprefix + profile_name)
                if profile_config.get('add_group_to_tag', True):
                    tagdict[tagname].add(thash)
                profiles_dict[profile_name].add(thash)
                break

        addtag = defaultdict(set)
        deltag = defaultdict(set)
        for sltag, hashes in tagdict.items():
            for thash in hashes:
                torrent = torrents[thash]
                torrenttags = set(torrent.tags.split(", "))
                if sltag not in torrenttags:
                    logger.debug(f"{self.name:<10} - adding tag {sltag} to {torrent.get('name')}")
                    addtag[sltag].add(thash)
        for thash, torrent in torrents.items():
            sltags = set(torrent.tags.split(", ")) & set(tagdict.keys()) # tags relativos a sharelimits
            for sltag in sltags:
                if thash not in tagdict[sltag]:
                    logger.debug(f"{self.name:<10} - removing tag {sltag} from {torrent.get('name')}")
                    deltag[sltag].add(thash)

        for group_name, hashes in profiles_dict.items():
            tagname = profiles[group_name].get('custom_tag', tagprefix + group_name)

            # ratio and limit
            p_maxratio = profiles[group_name].get('max_ratio', -2)
            p_maxtime = profiles[group_name].get('max_seeding_time', -2)
            p_uplimit = profiles[group_name].get('upload_limit', -2)

            if parse(p_maxtime) > 0:
                p_maxtime = int((parse(p_maxtime) / 60))
            if p_maxratio != None or p_maxtime != None:
                limits = {
                    'ratio': p_maxratio,
                    'time':p_maxtime
                }
            if len(hashes): logger.debug(f"{self.name:<10} - {len(hashes)} torrents {tagname}")
            client.sharelimit(hashes, limits)
            client.uploadlimit(hashes, p_uplimit)

        changes = 0
        for sltag, hashes in addtag.items():
            client.add_tags(hashes, sltag)
            changes += len(hashes)
        for sltag, hashes in deltag.items():
            client.remove_tags(hashes, sltag)
            changes += len(hashes)

        logger.info(f"{self.name:<10} - {changes} new sharelimits set")

        return changes

# ============================================
# AUX
# # ==========================================

def format_time_left(time_left_hours):
    # Convertimos el tiempo de horas a segundos
    time_left_seconds = time_left_hours * 3600
    time_left = timedelta(seconds=time_left_seconds)

    # Extraemos días, horas y minutos
    days = time_left.days
    hours, remainder = divmod(time_left.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    # Construimos
    time_str = ""
    if days > 0:
        time_str += f"{days}d "
    if hours > 0:
        time_str += f"{hours}h "
    if minutes > 0 or (days == 0 and hours == 0):
        time_str += f"{minutes}m"

    return time_str.strip()

def wait_for_event(name, wait_event, logger_prefix):
    if not wait_event.is_set():
        logger.debug(f"{logger_prefix:<10} - esperando {name}")
        wait_event.wait()
        logger.debug(f"{logger_prefix:<10} - {name} completado")

# ===========================================
