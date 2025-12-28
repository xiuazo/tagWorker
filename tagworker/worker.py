import os
import time
import threading
import traceback
import tldextract
import schedule

from collections import defaultdict
from datetime import timedelta
from pytimeparse2 import parse
from fnmatch import fnmatch

from .config import GlobalConfig
from .logger import logger
from .qbit import qBit
from .files import move_to_dir, is_file, build_inode_map, file_has_outer_links, translate_path, remove_empty_dirs

METHOD_API: int = 0
METHOD_DICT: int = 1

DEFAULT_ISSUE_METHOD: int = METHOD_API

SAFE_ORPHANS: int = 50

class worker:
    instances: set = set()
    reacted: dict = dict()

    new_torrents: bool = False


    def __init__(self, name: str, config, trackerissue_method: int = DEFAULT_ISSUE_METHOD, tag_interval: int = 15, disk_interval: int = 1800) -> None:
        self.client: qBit = qBit(config.url, config.user, config.password)
        self.config: GlobalConfig = config
        self.name: str = name or tldextract.extract(config['url']).domain
        self.commands: dict[str, bool] = getattr(config, 'commands', {})
        self.folders: dict[str, str] = getattr(config, 'folders', {})
        self.translation_table: dict[str, str] = getattr(config, 'translation_table', {})
        # self.share_limits: dict[str, GlobalConfig] = getattr(config, 'share_limits', {})
        self.share_limits: dict[str, dict[str, str]] = getattr(config, 'share_limits', {})
        self.dryrun: bool = getattr(config, 'dryrun', True)
        self.local_client: bool = getattr(config, 'local_instance', False)
        self.trackerissue_method: int = trackerissue_method

        self.changes_dict: set = set()
        self._full_update_time: float = 0

        self.tag_interval: int = tag_interval
        self.disk_interval: int = disk_interval

        # self.lock: threading.Lock = threading.Lock()
        self.tag_running: threading.Event = threading.Event()
        self.disk_running: threading.Event = threading.Event()

        self.__class__.reacted[self] = False
        self.__class__.instances.add(self)


    def run(self, singlerun: bool = False):
        if not self.verify_credentials(): return False

        if singlerun:
            self.task_tag()
            if self.local_client:
                self.task_disk()
            return None

        schedule.every(self.tag_interval).seconds.do(self.task_tag)
        self.task_tag()

        if self.local_client:
            schedule.every(self.disk_interval).seconds.do(self.task_disk)
            self.task_disk()
        return True


    @classmethod
    def get_instances(cls) -> set:
        return cls.instances


    @classmethod
    def all_instances_iterator(cls):
        for instance in cls.instances:
            yield instance


    # @property
    # def is_running(self) -> bool:
    #     return bool(self.tag_thread or self.disk_thread)


    def verify_credentials(self) -> bool:
        try:
            self.client.login()
            logger.info(f"{self.name:<10} - logged in")
            return True
        except Exception as e:
            logger.error(f"{self.name:<10} - unable to log in. client disabled. {e}")
            return False


    def logout(self) -> None:
        self.client.auth_log_out()


    def torrents_changed(self, prop):
        # obtengo la informacion de los cambios de los torrents
        changed_t = self.client.sync_data.get('torrents', {})
        # ahora filtro los que no han tenido cambios que nos importen
        watched_props = [prop] if isinstance(prop, str) else prop
        all_torrents = self.client.torrentdict
        return {th: all_torrents[th] for th, tv in changed_t.items() if not watched_props or (watched_props & tv.keys())}


    def task_tag(self) -> None:
        if self.tag_running.is_set() or self.disk_running.is_set():
            logger.warning(f"{self.name:<10} - Busy (Skipping run) ({self.tag_running.is_set() = } / {self.disk_running.is_set() = }) ")
            return

        self.tag_running.set()
        sl_torrent_queue = set()

        try:
            while True:
                prev_torrents = set(self.client.torrentdict.keys())

                request_fullsync = time.time() - self._full_update_time > parse(GlobalConfig.get('app.fullsync_interval'))
                if request_fullsync:
                    logger.info("%-10s - SYNCING WITH FULL DATA", self.name)
                    self._full_update_time = time.time()
                self.client.do_sync(request_fullsync)

                tag_funcs = {
                    'tag_trackers': self.tag_trackers,
                    'tag_HR': self.tag_HR,
                    'scan_no_tmm': self.tag_TMM,
                    'tag_issues': self.tag_issues,
                    'tag_rename': self.tag_rename,
                    'tag_lowseeds': self.tag_lowseeds,
                    'tag_HUNO': self.tag_HUNO,
                }

                tags_changed: bool = False
                for key, func in tag_funcs.items():
                    if self.commands.get(key, False):
                        changes = func()
                        if changes: logger.debug(f"{self.name:<10} - {key} made changes.")
                        tags_changed |= changes

                # curr_torrents = set(self.client.status.get('torrents', {}).keys())
                curr_torrents = set(self.client.torrentdict.keys())
                if curr_torrents != prev_torrents:
                    logger.info(f"{self.name:<10} - torrentlist changed. broadcasting need to check dupes")
                    # podria estar ya a true y con alguna instancia ya reaccionada. estas se lo podrian perder
                    self.__class__.reacted = {key: False for key in self.__class__.reacted}

                # si el usuario quiere, si han habido novedades desde el ultimo scan
                # ... y si el resto de instancias estan ya pobladas!
                # tag_dupes devuelve None si no encuentra ningun otro cliente poblado
                if GlobalConfig.get('app.dupes.enabled', False) and not self.__class__.reacted[self]:
                    try:
                        tags_changed |= self.tag_dupes()
                        self.__class__.reacted[self] = True
                    except Exception as e:
                        if str(e) != "Not all clients are synced": raise

                tags_changed |= self.clean_noHL()

                sl_torrent_queue |= set(self.torrents_changed({'state', 'category', 'max_seeding_time', 'up_limit', 'tags'}).keys())

                if tags_changed:
                    logger.debug(f"{self.name:<10} - changes have been made. looping...")
                    time.sleep(5)
                else:
                    # cuando los tags están en orden es cuando ajustamos SL
                    if self.commands.get('share_limits', False): self.set_sharelimits(sl_torrent_queue)
                    sl_torrent_queue.clear()
                    break
        finally:
            self.tag_running.clear()


    def task_disk(self) -> None:
        if not self.local_client:
            return

        BUSY_WAIT: int = 5
        while not self.client.synced:
            logger.warning(f"{self.name:<10} - Client not synced yet. Retrying in {BUSY_WAIT}s...")
            time.sleep(BUSY_WAIT)
        while self.tag_running.is_set():
            logger.warning(f"{self.name:<10} - Busy. Retrying in {BUSY_WAIT}s... ({self.tag_running.is_set() = }) ")
            time.sleep(BUSY_WAIT)
            # return
        if self.disk_running.is_set():
            logger.warning(f"{self.name:<10} - Busy. (Already executing. Skipping.)")
            return

        self.disk_running.set()

        commands: dict[str, bool] = self.commands
        dry_run: bool = self.dryrun
        tagged: bool = False
        logger.debug(f"{self.name:<10} - disk task started")

        try:

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
        finally:
            self.disk_running.clear()

        logger.debug(f"{self.name:<10} - disk task done")
        if tagged:
            logger.debug(f"{self.name:<10} - triggering tag task")
            threading.Thread(target=self.task_tag).start()
        # if singlerun: break


    def disk_orphans(self, dry_run: bool = True) -> None:
        root: str = os.path.abspath(self.folders["root_path"])
        orphan: str = os.path.abspath(self.folders["orphaned_path"])

        # patrones absolutos + POSIX
        pats: list[str] = [
            os.path.abspath(os.path.join(root, p)).replace(os.sep, "/")
            for p in self.folders.get("orphaned_ignored", [])
        ]

        def ignored(path: str) -> bool:
            p = path.replace(os.sep, "/")
            return any(fnmatch(p, pat) for pat in pats)

        # recopilar archivos
        hd_files: set[str] = set()

        for r, dirs, files in os.walk(root):
            r_abs: str = os.path.abspath(r)

            if r_abs.startswith(orphan):
                dirs[:] = []
                continue

            # filtrar dirs ignorados
            dirs[:] = [
                d for d in dirs
                if not ignored(os.path.abspath(os.path.join(r, d)))
            ]

            # añadir archivos no ignorados
            for f in files:
                full: str = os.path.abspath(os.path.join(r, f))
                if not ignored(full):
                    hd_files.add(os.path.normpath(full))

        # archivos referenciados
        total_referenced: set[str] = set()

        for thash, t in self.client.torrentdict.items():
            content_path: str = str(t.get("content_path"))
            if not content_path:
                # si no hay content_path, no hay referencia a comprobar
                continue

            p: str = translate_path(content_path, self.translation_table)
            p = os.path.abspath(p)
            referenced: set[str]

            if os.path.isfile(p):
                referenced = {os.path.normpath(p)}
            elif os.path.isdir(p):
                # obtener la lista de ficheros del torrent y normalizar rutas
                referenced = {
                    os.path.normpath(os.path.abspath(translate_path(f, self.translation_table)))
                    for f in self.client.torrent_files(thash)
                }
            else:
                if t.get("state") in ["error", "missingFiles"] or t.get("progress", 0) != 1:
                    continue
                logger.warning(f"Missing file: {t.get('name', '<unknown>')} - {p}")
                continue

            if total_referenced & referenced:
                logger.warning(
                    f"{self.name:<10} - Tracker-dupe? {t.get('name', '<unknown>')} "
                    f"({tldextract.extract(t.get('tracker', '')).domain}) files belong to multiple torrents"
                )

            total_referenced |= referenced

        # huérfanos
        orphans: set[str] = hd_files - total_referenced
        if not orphans:
            return

        logger.info(f"{self.name:<10} - {len(orphans)} orphan files moved to {orphan}")


        if len(orphans) > SAFE_ORPHANS:
            dry_run = True
            logger.warning(f"Found {len(orphans)} orphans. Enforcing dry-run!")
        for f in sorted(orphans):
            if dry_run:
                logger.info(f"{self.name:<10} - *** DRY-RUN *** moved {f} to {orphan}")
            else:
                move_to_dir(root, orphan, f)
                logger.info(f"{self.name:<10} - moved {f} to {orphan}")



    def disk_prune_old(self, dry_run: bool = True) -> None:
        path: str = self.folders.get('orphaned_path', '')
        expire_time: float = parse(GlobalConfig.get("app.prune_orphaned_time", 0))

        time_limit: float = time.time() - expire_time
        files_to_delete: set[str] = set()

        for root, _, files in os.walk(path):
            for filename in files:
                fullpath: str = os.path.join(root, filename)
                mod_time: float = os.path.getmtime(fullpath)
                if mod_time < time_limit:
                    files_to_delete.add(fullpath)

        if files_to_delete:
            logger.info(f"%-10s - Deleting {len(files_to_delete)} old orphans.", self.name)
            try:
                for fullpath in files_to_delete:
                    if not dry_run:
                        os.remove(fullpath)
                        logger.info(f"%-10s - Deleted {os.path.basename(fullpath)}", self.name)
                    else:
                        logger.info(f"%-10s - *** DRY-RUN *** deleted {os.path.basename(fullpath)}", self.name)
            except Exception as e:
                logger.warning(f'%-10s - Error trying to delete file {fullpath}: {e}', self.name)


    def disk_noHL(self) -> bool:
        # creamos una lista con todos los inodos dentro del root_path y cuantas veces aparecen
        # posteriormente miramos los torrents uno a uno
        # si tiene HL fuera, el fichero deberia tener una cantidad de links superior a los que hemos encontrado
        #
        # en caso de multifile miraremos fichero a fichero sus contenidos hasta encontrar alguno que si tenga HL fuera
        def torrent_has_HL(torrent, inode_map, translation_table) -> bool:
            # TODO en que situacion esta vacio?? soltar excepcion?? continuar??
            # try:
            content_path: str|None = torrent.get("content_path", None)
            if not content_path:
                raise Exception(f"Torrent {torrent.get('name', '')} has no content path.")
            # except:
                # pass
            realfile: str = translate_path(content_path, translation_table)
            if is_file(realfile):
                return file_has_outer_links(realfile, inode_map)
            # FIXME iterar contenidos del content_path. si hay algun HL lo damos por bueno
            for root, _, files in os.walk(translate_path(content_path, translation_table)):
                for file in files:
                    realfile = translate_path(file, translation_table)
                    fullpath: str = os.path.join(root, realfile)
                    if file_has_outer_links(fullpath, inode_map):
                        return True
            return False

        root_path: str|None = self.folders.get('root_path', None)
        if not root_path:
            raise Exception("Root path not set")
        translation_table: dict[str, str] = self.translation_table
        noHL_tag: str = GlobalConfig.get("app.noHL.tag")
        noHL_cats: str = GlobalConfig.get("app.noHL.categories")

        torrents: dict[int, dict[str, str]]= self.client.torrentdict

        if not torrents:
            return False
        inode_map: dict[int, int] = build_inode_map(root_path)
        noHLs, addtag, deltag = set(), set(), set()
        for thash, torrent in torrents.items():
            # if torrent.get("category") not in noHL_cats:
                # continue

            tagged: bool = noHL_tag in torrent.get("tags", "").split(", ")

            if torrent.get("category", '') in noHL_cats and torrent.get("progress", 0) == 1 and not torrent_has_HL(torrent, inode_map, translation_table):
                noHLs.add(thash)
                if not tagged:
                    logger.info(f"{self.name:<10} - noHL: {torrent.get('name')}")
                    addtag.add(thash)
            elif tagged:
                logger.info(f"{self.name:<10} - found link for: {torrent.get('name', 'Unknown')}")
                deltag.add(thash)

        if addtag or deltag:
            if addtag: self.client.add_tags(addtag, noHL_tag)
            if deltag: self.client.remove_tags(deltag, noHL_tag)
            logger.info(f"{self.name:<10} - {len(noHLs)} noHL. New {len(addtag)} - Untagged {len(deltag)}")
            return True
        return False

    def clean_noHL(self) -> bool:
        """
        Si la instancia no es local no hace nada -> no limpia pq podria haber otro gestor
        Elimina los tags de noHL cuando:
         - un torrent pertenece a una categoria fuera del scan
         - noHL está deshabilitado
        """
        if not self.local_client:
            return False
        noHL_tag: str = GlobalConfig.get("app.noHL.tag", '')
        if not noHL_tag:
            raise Exception("noHL tag not set")

        noHL_cats: list[str] = GlobalConfig.get("app.noHL.categories", [])
        torrents: dict[str, dict[str, str]] = self.torrents_changed({'category', 'tags'})
        torrents = {th: tval for th, tval in torrents.items() if noHL_tag in tval['tags'].split(", ")} # filter torrents by noHL tag
        hashes: set[str] = set()
        if not self.commands.get('tag_noHL'):
            hashes.update(set(torrents.keys()))
            if hashes: logger.info(f"{self.name:<10} - Untagged {noHL_tag} {len(torrents)} torrents: tag_noHL command disabled")
        else:
            for thash, torrent in torrents.items():
                if torrent.get('category', '') not in noHL_cats:
                    logger.info(f"{self.name:<10} - Untagged {noHL_tag} {torrent.get('name')}: disabled category")
                    hashes.add(thash)
        if hashes:
            self.client.remove_tags(hashes, noHL_tag)
        return bool(hashes)

    def tag_lowseeds(self) -> bool:
        torrents: dict[str, dict[str, str]] = self.torrents_changed({'num_complete', 'tags', 'tracker', 'state'})
        if not torrents:
            return False

        addtag: set = set()
        deltag: set = set()
        tag: str = GlobalConfig.get("app.lowseeds.tag", '')
        min_seeds: int = GlobalConfig.get("app.lowseeds.min_seeds", 0)
        for thash, torrent in torrents.items():
            tags: list[str] = torrent.get("tags", "").split(", ")
            seeds: int = int(torrent.get('num_complete', 0))
            if torrent.get("progress", 0) != 1 or torrent.get('state','') in ['stoppedUP', 'pausedUP', 'pausedDL', 'error', 'unknown']: # filtramos solos los que estan vivos XD
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

    def tag_dupes(self) -> bool:
        if not len(self.__class__.instances) > 1: # 1 is me!
            logger.warning(f"{self.name:<10} - no other clients. skipping dupe tagging")
            return False
        torrents: set[str] = set()
        for instance in self.__class__.all_instances_iterator():
            if instance == self: continue # my torrents are not dupes!
            if not instance.client.synced:
                logger.warning(f"{self.name:<10} - not all clients are synced. skipping dupe tagging")
                raise Exception("Not all clients are synced")
            torrents.update(instance.client.torrentdict.keys())

        my_torrents: dict[str, dict[str, str]] = self.client.torrentdict
        dupes: set[str] = torrents & set(my_torrents.keys())
        dupetag: str = GlobalConfig.get("app.dupes.tag", '')

        addtag: set[str] = set()
        deltag: set[str] = set()
        for thash, tval in my_torrents.items():
            tags = my_torrents[thash]['tags'].split(", ")
            if dupetag in tags:
                if thash not in dupes:
                    logger.debug(f"{self.name:<10} - {tval['name']} should not be marked as dupe")
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
            ttags = torrent.get("tags", "").split(", ")
            if torrent.get('state') in ['stoppedUP', 'pausedUP','pausedDL', 'error', 'unknown']:
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
                    elif tracker.get('status') != 0:
                        errormsg = tracker.get('msg')
            else:
                errormsg = ''
                working = torrent.get('tracker')
            if not working:
                if errortag not in ttags:
                    logger.debug(f"{self.name:<10} - errored {tldextract.extract(torrent['tracker']).domain}: {torrent['name']} {'(' + errormsg + ')' if errormsg else ''}")
                    errored.add(thash)
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
            torrent_tags = torrent.get("tags", "").split(", ")

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
                            logger.debug(f"{self.name:<10} - {torrent.name} now satisfied.")
                            satisfied.add(thash)
                    # H&R
                    else:
                        if hr_tag not in torrent_tags:
                            unsatisfied.add(thash)
                        if torrent['state'] in {'stoppedUP', 'pausedUP'}:  # y queuedUP ??
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

    def tag_TMM(self) -> bool:
        torrents = self.torrents_changed({'auto_tmm', 'tags', 'category'})
        client = self.client
        config = GlobalConfig.get("app.noTMM")

        if not torrents:
            return False

        logger.info(f'%-10s - checking {len(torrents)} torrents autoTMM', self.name)

        tag: str = config.tag
        ignoredtags: set[str] = getattr(config, 'ignored_tags', set())
        ignoredcats: set[str] = getattr(config, 'ignored_categories', set())
        tag_add: set[str] = set()
        tag_remove: set[str] = set()
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
            hashes = {th for th, tv in client.torrentdict.items() if old_tag in tv.get("tags", "").split(", ")}
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
            torrent_tags = set(torrent.get("tags", "").split(", "))

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

    def set_sharelimits(self, torrentset) -> bool:
        if not torrentset: return False
        torrents = {thash : self.client.torrentdict.get(thash) for thash in torrentset}

        # logger.debug(f"{self.name:<10} - checking {len(torrents)} torrents sharelimits")

        profiles: dict[str, dict[str, str]] = dict(self.share_limits)
        tagprefix = GlobalConfig.get("app.share_limits_tag_prefix")
        profiles_dict: dict[str, set] = dict()
        tagdict: dict[str, set] = dict()

        # lo inicializo con todos los nombres para que hayan items o no, se recorra para tag Y UNTAG
        for profile_name, profile_config in profiles.items():
            tagname: str = profile_config.get('custom_tag', tagprefix + profile_name)
            profiles_dict[profile_name] = set()
            tagdict[tagname] = set()

        # CLASIFICAR TORRENTS
        for thash, torrent in torrents.items():
            if not torrent:
                logger.warning(f"{self.name:<10} - skipping hash {thash}. ")
                continue
            # no categorizo si no está completo
            if torrent.get("progress", 0) != 1: continue

            tags = torrent.get("tags", "").split(", ")
            # find matching profile
            for profile_name, profile_config in profiles.items():
                pc = dict(profile_config)
                if (
                    ('category' in pc and not any(cat == torrent.get('category') for cat in pc['category']))
                    or ('include_all_tags' in pc and not all(tag in tags for tag in pc['include_all_tags']))
                    or ('include_any_tags' in pc and not any(tag in tags for tag in pc['include_any_tags']))
                    or ('exclude_all_tags' in pc and all(tag in tags for tag in pc['exclude_all_tags']))
                    or ('exclude_any_tags' in pc and any(tag in tags for tag in pc['exclude_any_tags']))
                ):
                    continue

                tagname = pc.get('custom_tag', tagprefix + profile_name)
                if pc.get('add_group_to_tag', True):
                    tagdict[tagname].add(thash)
                profiles_dict[profile_name].add(thash)
                break

        # DICCIONARIOS PARA TAGUEADO, DESTAGUEADO
        addtag = defaultdict(set)
        deltag = defaultdict(set)
        for sltag, hashes in tagdict.items():
            for thash in hashes:
                torrent = torrents[thash]
                torrenttags = set(torrent.get("tags", "").split(", "))
                if sltag not in torrenttags:
                    logger.debug(f"{self.name:<10} - adding tag {sltag} to {torrent.get('name')}")
                    addtag[sltag].add(thash)
        for thash, torrent in torrents.items():
            sltags = set(torrent.get("tags","").split(", ")) & set(tagdict.keys()) # tags relativos a sharelimits
            for sltag in sltags:
                if thash not in tagdict[sltag]:
                    logger.debug(f"{self.name:<10} - removing tag {sltag} from {torrent.get('name')}")
                    deltag[sltag].add(thash)

        # APLICACION DE SHARELIMITS Y GENERACION DE LISTA PARA RESUME
        sharelimits_changed = 0
        resume = set()
        delete = set()
        for group_name, hashes in profiles_dict.items():
            tagname = profiles[group_name].get('custom_tag', tagprefix + group_name)
            # logger.debug(f"{self.name:<10} - {len(hashes)} torrents {tagname}")

            # ratio and limit
            p_maxratio = profiles[group_name].get('max_ratio', -2)
            p_maxtime = profiles[group_name].get('max_seeding_time', -2)
            p_uplimit = profiles[group_name].get('upload_limit', -2)
            p_autoresume = profiles[group_name].get('auto_resume', True) # ? buen default??
            p_autodelete = profiles[group_name].get('auto_delete', False)

            if parse(p_maxtime) > 0:
                p_maxtime = int((parse(p_maxtime) / 60))
            if p_maxratio != None or p_maxtime != None:
                limits = {
                    'ratio': p_maxratio,
                    'time':p_maxtime
                }

            fix_hashes = set()
            for h in hashes:
                torrent = torrents[h]
                if (
                    (torrent['ratio_limit'] != p_maxratio)
                    or (torrent['seeding_time_limit'] != p_maxtime)
                    or (torrent['up_limit'] > 0 and torrent['up_limit'] != p_uplimit * 1024)
                ):
                    logger.debug(f"{self.name:<10} - Changing {torrent.get('name')} sharelimit to {group_name} profile.")
                    fix_hashes.add(h)

                maxtime = torrent['max_seeding_time'] * 60
                completed = maxtime >= 0 and maxtime < torrent['seeding_time']
                if p_autoresume:
                    if torrent.get('state') in ['stoppedUP', 'pausedUP'] and not completed:
                        # FIXME
                        logger.debug(f"{self.name:<10} - Resuming {torrent.get('name')}.")
                        resume.add(h)

                if p_autodelete:
                    if completed and torrent.get('state') in ['stoppedUP', 'pausedUP']:
                        logger.debug(f"{self.name:<10} - Torrent {torrent.get('name')} marked for autodeletion.")
                        delete.add(h)


            if len(fix_hashes):
                sharelimits_changed += len(fix_hashes)
                self.client.sharelimit(fix_hashes, limits)
                self.client.uploadlimit(fix_hashes, p_uplimit)

        # APLICACION DE TAGS Y RESUME
        tags_changed = 0
        for sltag, hashes in addtag.items():
            self.client.add_tags(hashes, sltag)
            tags_changed += len(hashes)
        for sltag, hashes in deltag.items():
            self.client.remove_tags(hashes, sltag)
            tags_changed += len(hashes)
        if resume:
            self.client.start(resume)
        if delete:
            self.client.add_tags(delete, "!DELETE")

        if tags_changed:
            logger.info(f"{self.name:<10} - {tags_changed} tags changed")
        if sharelimits_changed:
            logger.info(f"{self.name:<10} - {sharelimits_changed} sharelimits set")
        if resume:
            logger.info(f"{self.name:<10} - {len(resume)} torrents resumed")

        return bool(tags_changed or sharelimits_changed or resume)

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
