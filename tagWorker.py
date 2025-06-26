import sys
import os
import time
import threading
import uuid
import traceback
import platform
import tldextract

from collections import defaultdict
from datetime import timedelta
from pytimeparse2 import parse

from modules.config import Config
from modules.logger import logger
from modules.qbit import qBit
from modules.files import move_to_dir, is_file, build_inode_map, verificar_hardlinks, translate_path

def print_banner(version="0.0.1"):
    # ANSI codes
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    FG_WHITE = "\033[37m"
    FG_YELLOW = "\033[33m"
    FG_CYAN = "\033[36m"
    FG_GREEN = "\033[32m"
    # Disable if not interactive terminal
    if not sys.stdout.isatty():
        RESET = BOLD = DIM = FG_WHITE = FG_YELLOW = FG_CYAN = FG_GREEN = ""

    banner = fr"""
   __             _       __           __
  / /_____ _____ | |     / /___  _____/ /_____  _____
 / __/ __ `/ __ `/ | /| / / __ \/ ___/ //_/ _ \/ ___/
/ /_/ /_/ / /_/ /| |/ |/ / /_/ / /  / ,< /  __/ /
\__/\__,_/\__, / |__/|__/\____/_/  /_/|_|\___/_/
         /____/

"""

    print(f"{FG_CYAN}{banner}{RESET}")
    print("-" * 72)
    print(f"{BOLD}Version         : {FG_GREEN}{version}{RESET}")
    print(f"{BOLD}License         : {FG_YELLOW}GNU General Public License v3.0{RESET}")
    print(f"{BOLD}                  {DIM}https://www.gnu.org/licenses/gpl-3.0.html{RESET}")
    print(f"{BOLD}Copyright       : {FG_CYAN}(C) 2025 xiu{RESET}")
    print(f"{BOLD}                  {FG_CYAN}https://github.com/xiuazo/tagWorker{RESET}")
    print(f"{BOLD}                  {FG_WHITE}This is free software. You may modify and")
    print(f"{BOLD}                  {FG_WHITE}redistribute it under the same license.{RESET}")
    print("-" * 72)

print_banner()


# =========================================================================

class TagWorker:
    appconfig = {}
    instances = []

    new_torrents = False
    instance_reactions = {}

    def __init__(self, qbit, config):
        self.id = uuid.uuid4()
        self.client = qbit
        self.commands = config['commands']
        self.folders = config.get('folders')
        self.translation_table = config.get('translation_table',[])
        self.share_limits = config['share_limits']
        self.name = config.get('name', tldextract.extract(config['url']).domain)
        self.changes_dict = {}
        self.dryrun = config.get("dryrun", True)
        self.localinstance = config.get("local_instance", False)
        self._full_update_time = 0

        self.stop_event = threading.Event()
        self.tag_idle = threading.Event()
        self.tag_trigger = threading.Event()
        self.disk_idle = threading.Event()
        # si tags espera por el disco y el disco espera por tags... malo. iniciamos asi para iniciar por los tags (es quien hace sync)
        self.tag_idle.clear()
        self.disk_idle.set()

        self.__class__.instances.append(self)
        self.__class__.instance_reactions[self] = False

    def run(self):
        try:
            self.client.login()
            logger.info(f"{self.name:<10} - logged in")
        except Exception as e:
            logger.error(f"{self.name:<10} - unable to log in. client disabled. {e}")
            return None, None

        tag = threading.Thread(target=self.task_tag)
        disk = threading.Thread(target=self.task_disk)
        tag.start()
        disk.start()

        return tag, disk

    def torrents_changed(self, prop = None):
        # obtengo la informacion de los cambios de los torrents
        changed_t = self.client.changes.get('torrents', {})
        # ahora filtro los que no han tenido cambios que nos importen
        watched_props = [prop] if isinstance(prop, str) else prop
        all_torrents = self.client.status.get('torrents', {})
        return {th: all_torrents[th] for th, tv in changed_t.items() if not watched_props or (watched_props & tv.keys())}

    def task_tag(self):
        commands = self.commands
        sl_torrent_queue = set()

        while not self.stop_event.is_set():
            wait_for_event("disk_done", self.disk_idle, self.name)
            self.tag_idle.clear()

            prev_torrents = set(self.client.status.get('torrents', {}).keys())

            request_fullsync = time.time() - self._full_update_time > parse(TagWorker.appconfig.fullsync_interval)
            self.client.sync(request_fullsync)
            if request_fullsync:
                logger.info("%-10s - SYNCING WITH FULL DATA", self.name)
                self._full_update_time = time.time()

            curr_torrents = set(self.client.status.get('torrents', {}).keys())
            if curr_torrents != prev_torrents:
                logger.info(f"{self.name:<10} - torrentlist changed. broadcasting need to check dupes")
                # podria estar ya a true y con alguna instancia ya reaccionada. estas se lo podrian perder
                TagWorker.instance_reactions = {key: False for key in TagWorker.instance_reactions}

            tags_changed = False

            if TagWorker.appconfig.scan_dupes and not TagWorker.instance_reactions[self]:
                tags_changed |= self.tag_dupes()
                TagWorker.instance_reactions[self] = True

            tag_funcs = {
                'tag_trackers': self.tag_trackers,
                'tag_HR': self.tag_HR,
                'scan_no_tmm': self.tag_TMM,
                'tag_issues': self.tag_issues,
                'tag_rename': self.tag_rename,
                'tag_lowseeds': self.tag_lowseeds,
                'tag_HUNO': self.tag_HUNO,
            }

            for key, func in tag_funcs.items():
                if commands.get(key, False):
                    changes = func()
                    if changes: logger.debug(f"{self.name:<10} - {key} made changes.")
                    tags_changed |= changes

            tags_changed |= self.clean_noHL()

            sl_torrent_queue |= set(self.torrents_changed({'category', 'max_seeding_time', 'up_limit', 'tags'}).keys())

            if not tags_changed:
                # cuando los tags están en orden es cuando ajustamos SL
                if commands.get('share_limits', False): self.tag_SL(sl_torrent_queue)
                sl_torrent_queue.clear()
                # logger.debug(f"{self.name:<10} - sleeping {parse(TagWorker.appconfig.tagging_schedule_interval)}s...")
                self.tag_idle.set()
                self.tag_trigger.wait(timeout=parse(TagWorker.appconfig.tagging_schedule_interval))
                self.tag_trigger.clear()
            else:
                logger.debug(f"{self.name:<10} - changes have been made. looping...")
                self.stop_event.wait(2) # delay para que qbit aplique cambios. no uso tag_trigger pq no quiero que disk_task lo arranque. es un delay interrumpible, sin mas

    def task_disk(self):
        commands = self.commands
        if not self.localinstance:
            self.disk_idle.set()
            return

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
                    self.disk_clean_orphans()

                if commands.get('prune_orphaned'):
                    # logger.info(f"{self.name:<10} - pruning old orphans")
                    self.disk_prune_old()
            except Exception as e:
                logger.error(f"Error: {e}\n{traceback.format_exc()}")

            logger.info(f"{self.name:<10} - disk task done")
            self.disk_idle.set()
            if tagged:
                logger.debug(f"{self.name:<10} - triggering tag task")
                self.tag_trigger.set()
            self.stop_event.wait(timeout=parse(TagWorker.appconfig.disktasks_schedule_interval))

    def disk_clean_orphans(self):
        root_path = self.folders.get('root_path')
        orphan_path = self.folders.get('orphaned_path')

        # Forma el set con todos los archivos de todos los torrents
        referenced_files = set()
        torrents = self.client.status.get('torrents', {})
        for thash in torrents.keys():
            files = self.client.get_torrent_files(thash) # no normalizado
            referenced_files.update(files)
        referenced_files = {translate_path(f, self.translation_table) for f in referenced_files}

        # Recorre el árbol de directorios y excluye el directorio de huerfanos
        hd_files = set()
        for root, dirs, files in os.walk(root_path):
            if root_path.startswith(orphan_path):
                dirs[:] = []
            else:
                # Exclusion
                dirs[:] = [d for d in dirs if not os.path.join(root, d).startswith(orphan_path)]

            for file in files:
                ruta_archivo = os.path.join(root, file)
                hd_files.add(ruta_archivo)

        # Calcula los archivos huérfanos
        orphaned_files = hd_files - referenced_files
        if not len(orphaned_files):
            return

        # TODO
        # if len(orphaned_files) > 10:
        #     return
        logger.info(f'%-10s - {len(orphaned_files)} orphan files moved to {orphan_path}', self.name)
        for file in sorted(orphaned_files):
            if not self.dryrun:
                move_to_dir(root_path, orphan_path, file)
                logger.info(f"%-10s - moved {file} to {orphan_path}", self.name)
            else:
                logger.info(f"%-10s - *** DRY-RUN *** moved {file} to {orphan_path}", self.name)
        # remove_empty_dirs(root_path, url)

    def disk_prune_old(self):
        path = self.folders.get('orphaned_path')
        expire_time = parse(TagWorker.appconfig.prune_orphaned_time)

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
                    if not self.dryrun:
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
        raiz = self.folders.get('root_path')
        torrents = self.client.status.get('torrents', {})
        translation_table = self.translation_table

        if torrents:
            inodo_mapa = build_inode_map(raiz)
        noHLs, addtag, deltag = set(), set(), set()
        noHL_tag = TagWorker.appconfig.noHL_tag
        for thash, torrent in torrents.items():
            tagged = noHL_tag in torrent['tags'].split(", ")
            if torrent['category'] not in TagWorker.appconfig.noHL_categories:
                continue

            file = torrent['content_path']
            realfile = translate_path(file, translation_table)
            if not is_file(realfile):
                # FIXME iterar contenidos del content_path. si hay algun HL lo damos por bueno
                resultado = False
                for root, _, files in os.walk(translate_path(torrent['content_path'], translation_table)):
                    for file in files:
                        realfile = translate_path(file, translation_table)
                        ruta_archivo = os.path.join(root, realfile)
                        if verificar_hardlinks(ruta_archivo, inodo_mapa):
                            resultado = True
                            break
                    if resultado:
                        break
            else:
                resultado = verificar_hardlinks(realfile, inodo_mapa)
            if not resultado:
                noHLs.add(thash)
                if not tagged:
                    logger.info(f"{self.name:<10} - new noHL: {torrent.get('name')}")
                    addtag.add(thash)
            elif tagged:
                logger.info(f"{self.name:<10} - {torrent.get('name')} has links now.")
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
        if not self.localinstance:
            return False
        noHL_tag = TagWorker.appconfig.noHL_tag
        torrents = self.torrents_changed({'category', 'tags'})
        torrents = {th: tval for th, tval in torrents.items() if noHL_tag in tval['tags'].split(", ")} # filter torrents by noHL tag
        if not self.commands.get('tag_noHL'):
            hashes = torrents.keys()
            if hashes: logger.info(f"{self.name:<10} - Untagged {noHL_tag} {len(torrents)} torrents: tag_noHL command disabled")
        else:
            hashes = set()
            for thash, torrent in torrents.items():
                if torrent.get('category') not in TagWorker.appconfig.noHL_categories:
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
        tag = TagWorker.appconfig.lowseeds_tag
        for thash, torrent in torrents.items():
            tags = torrent.get('tags').split(', ')
            seeds = torrent.get('num_complete')
            if torrent.get('state','') in ['pausedUP','pausedDL', 'error', 'unknown']: # filtramos solos los que estan normal XD
                continue
            if seeds < TagWorker.appconfig.min_seeds and isinstance(seeds, int):
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
        config = TagWorker.appconfig

        torrents = set()
        multiple_instances = False
        for uid, tset in qBit.all_torrents_iterator():
            if uid == self.client._uid: continue # my torrents are not dupes!
            torrents.update(tset.keys())
            multiple_instances = True
        if not multiple_instances:
            logger.warning(f"{self.name:<10} - no other clients. skipping dupe tagging")
            return False

        my_torrents = self.client.status.get('torrents', {})
        my_hashes = set(my_torrents.keys())
        dupes = torrents & my_hashes

        addtag = set()
        deltag = set()
        for thash, tval in my_torrents.items():
            tags = my_torrents[thash]['tags'].split(", ")
            if config.dupe_tag in tags:
                if thash not in dupes:
                    logger.debug(f"{self.name:<10} - {tval['name']} is a NOT dupe but it's tagged")
                    deltag.add(thash)
            elif thash in dupes:
                    logger.debug(f"{self.name:<10} - {tval['name']} is a dupe")
                    addtag.add(thash)

        if addtag: self.client.add_tags(addtag, config.dupe_tag) # taguea dupes
        if deltag: self.client.remove_tags(deltag, config.dupe_tag)

        logger.info(f"{self.name:<10} - Found {len(dupes)} dupes across all clients. Tagged {len(addtag)} - Untagged {len(deltag)}")

        return bool(addtag or deltag)

    def tag_issues(self):
        torrents = self.torrents_changed({'tracker', 'state', 'tags'})

        if not torrents:
            return False

        errored, unerrored = set(), set()
        errortag = TagWorker.appconfig.issue_tag
        for thash, torrent in torrents.items():
            ttags = torrent.get('tags').split(", ")
            if torrent.get('state') in ['pausedUP','pausedDL', 'error', 'unknown']:
                if errortag in ttags:
                    unerrored.add(thash)
                continue
            response = self.client.get_trackers(thash)
            working = False
            errormsg = ""
            for tracker in response:
                if tracker.get('status') not in {0,4}:
                    working = True
                    break
                else: errormsg = tracker.get('msg')
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

        tracker_rules = TagWorker.appconfig.trackers_HR_rules
        hr_tag = TagWorker.appconfig.hr_tag
        exclude_xseed = TagWorker.appconfig.exclude_xseed
        autostart_hr = TagWorker.appconfig.autostart_hr

        unsatisfied = set()
        satisfied = set()
        autostart = set()

        for thash, torrent in torrents.items():
            seeding_time = torrent['seeding_time']
            torrent_ratio = torrent['ratio']
            torrent_tags = torrent.get('tags', '').split(", ")

            for key, (req_time, min_ratio, percent) in tracker_rules.items():
                if any(word in torrent['tracker'] for word in key.split("|")):
                    # satisfied
                    if (
                        (seeding_time > req_time)
                        or (min_ratio is not None and torrent_ratio > min_ratio)
                        or (exclude_xseed and torrent['downloaded'] == 0)
                        or (percent and (torrent['downloaded'] < (percent/100) * torrent['size']))
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
            return TagWorker.appconfig.huno_tag_prefix + name
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
        config = TagWorker.appconfig

        if not torrents:
            return False

        logger.info(f'%-10s - checking {len(torrents)} torrents autoTMM', self.name)

        tag = config.noTMM_tag
        ignoredtags = set(config.tmm_ignoretags or {})
        ignoredcats = set(config.tmm_ignored_categories or {})
        tag_add = set()
        tag_remove = set()
        for thash, tval in torrents.items():
            ttags = set(tval['tags'].split(', '))
            if tval['auto_tmm'] or ttags & ignoredtags or tval['category'] in ignoredcats:
                # no deberia tenerlo
                if tag in ttags:
                    tag_remove.add(thash)
                continue
            # si deberia tenerlo
            tag_add.add(thash)

        if tag_add:
            # si activamos el tmm ya no hace falta taguearlo
            if config.enable_tmm:
                client.enable_tmm(tag_add)
            else:
                client.add_tags(tag_add, tag)
        if tag_remove:
            client.remove_tags(tag_remove, tag)

        return bool(tag_add or tag_remove)

    def tag_rename(self):
        client = self.client
        tags_to_rename = TagWorker.appconfig.tags_to_rename
        # obtengo la informacion de los cambios de los torrents
        changed_t = client.changes.get('tags', {}) & tags_to_rename.keys()

        if not changed_t:
            # logger.debug(f'%-10s - no tags to rename', self.name)
            return False

        logger.info(f'%-10s - {changed_t} must be renamed.', self.name)

        torrents = client.status.get('torrents', {})
        for old_tag, new_tag in tags_to_rename.items():
            if old_tag not in changed_t:
                continue
            hashes = {th for th, tv in torrents.items() if old_tag in tv.get('tags','').split(", ")}
            client.add_tags(hashes, new_tag)

        self.client.delete_tags(tags_to_rename.keys()) # FIXME
        return True

    def tag_trackers(self):
        torrents = self.torrents_changed({'tracker', 'tags'})
        client = self.client
        config = TagWorker.appconfig

        if not torrents:
            return False

        tracker_details = config.tracker_details
        try:
            default_tag = tracker_details['default']['tag']
        except KeyError:
            logger.warning(f"{self.name:<10} - tracker_details['default']['tag'] no está definido")
            default_tag = None

        addtag = defaultdict(set)
        deltag = defaultdict(set)

        for thash, torrent in torrents.items():
            torrent_tracker = torrent.get('tracker')
            if not torrent_tracker: continue
            good_tags, bad_tags = set(), set()
            torrent_tags = set(torrent.get('tags', '').split(", "))

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
        tagprefix = TagWorker.appconfig.share_limits_tag_prefix
        profiles_dict = dict()
        tagdict = dict()

        # lo inicializo con todos los nombres para que hayan items o no, se recorra para tag Y UNTAG
        for profile_name, profile_config in profiles.items():
            tagname = profile_config.get('custom_tag', tagprefix + profile_name)
            profiles_dict[profile_name] = set()
            tagdict[tagname] = set()

        torrents = {thash : self.client.status.get('torrents', {}).get(thash) for thash in torrentset}

        for thash, tval in torrents.items():
            if not tval:
                logger.warning(f"{self.name:<10} - skipping hash {thash}. ")
                continue
            tags = tval.get('tags',{}).split(", ")
            # find matching profile
            for profile_name, profile_config in profiles.items():
                if (
                    ('category' in profile_config and not any(cat == tval['category'] for cat in profile_config['category']))
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
                torrenttags = set(torrent.get('tags', '').split(", "))
                if sltag not in torrenttags:
                    logger.debug(f"{self.name:<10} - adding tag {sltag} to {torrent.get('name')}")
                    addtag[sltag].add(thash)
        for thash, torrent in torrents.items():
            sltags = set(torrent.get('tags', '').split(", ")) & set(tagdict.keys()) # tags relativos a sharelimits
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

def startup_msg(config=None):
    print('')
    logger.info(f"Platform        : {platform.system()} {platform.release()}")
    logger.info(f"Python          : {platform.python_version()}")
    logger.info(f"qBit clients    : {len(config.qb_instances)}")

    if config:
        tracker_HR_rules = len(config.trackers_HR_rules)
        logger.info(f"FullSync every  : {getattr(config, 'fullsync_interval', 'N/A')}")
        logger.info(f"Refresh interval: {getattr(config, 'tagging_schedule_interval', 'N/A')}")
        logger.info(f"Disk Schedule   : {getattr(config, 'disktasks_schedule_interval', 'N/A')}")
        logger.info(f"Scan Dupes      : {getattr(config, 'scan_dupes', 'N/A')}")
        logger.info(f"Trackers        : {tracker_HR_rules}")
    print('')


def main():
    logger.info("%-10s - Logger init", "GLOBAL")
    config = Config()
    startup_msg(config=config)
    TagWorker.appconfig = config
    threads = []
    # inits
    for qb in config.qb_instances:
        if not qb.get('enabled', True):
            continue
        qbit = qBit(qb['url'], qb['user'], qb['password'], qb['commands'])
        try:
            instance = TagWorker(qbit, qb)
        except Exception as e:
            logger.critical(f"{qb['name']:<10} - {e} {str(e)}")
        # engage!
        try:
            threads.extend(instance.run())
        except Exception as e:
            logger.error(f"%-10s - Failed to init instance: {e}", qb['name'])

    # keep the main thread alive
    try:
        while True:
            time.sleep(300)
    except (KeyboardInterrupt, SystemExit):
        for instance in TagWorker.instances:
            try:
                logger.info(f'%-10s - Stopping instance', instance.name)
                instance.stop_event.set()
                instance.tag_trigger.set()
                instance.client.logout()
            except Exception as e:
                logger.error(f"%-10s - Unable to stop instance", instance.name)

    for t in threads:
        # comprobamos el tipo. si la instancia falló al loguear qbit, sus threads no existen y son None
        if isinstance(t, threading.Thread):
            t.join()

if __name__ == "__main__":
    # os.system("cls" if os.name == "nt" else "clear")
    main()
