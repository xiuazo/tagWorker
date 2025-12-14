import os
import qbittorrentapi

from .files import is_file

def deep_merge(target, source):
    for key, value in source.items():
        if isinstance(value, dict):
            # Si el valor es un diccionario, hacemos una fusión recursiva
            node = target.setdefault(key, {})
            deep_merge(node, value)
        else:
            # Si no es diccionario, actualizamos el valor en el target
            target[key] = value
            # if value is None or value == '':
            #     print(f'Valor vacio para clave {key}')
    return target

class qBit(qbittorrentapi.Client):
    def __init__(self, url, user, pwd):
        super().__init__(host=url, username=user, password=pwd)
        self.__rid = None
        self.__sync_data = None
        self.__state = dict()

    @property
    def synced(self):
        return self.__rid is not None

    @property
    def torrentdict(self):
        return self.__state.get('torrents', {})

    @property
    def sync_data(self):
        return self.__sync_data

    @property
    def status(self):
        return self.__state

    def do_sync(self, fullsync = False):
        if fullsync: self.sync.maindata.reset_rid()
        sync_data = self.sync.maindata.delta()

        full_update = sync_data.get("full_update", False)
        # torrents = sync_data.get("torrents", {})
        torrents_removed = list(sync_data.get("torrents_removed", []))
        # categories = sync_data.get("categories", {})
        # categories_removed = sync_data.get("categories_removed", {})
        # tags = sync_data.get("tags", {})
        # tags_removed = sync_data.get("tags_removed", {})
        # server_state = sync_data.server_state
        # trackers = sync_data.get("trackers")

        self.__sync_data = sync_data

        if full_update:
            self.__state = sync_data
        elif sync_data:
            # this drags obsolete data unless we clean. but we only care about torrents
            self.__state = deep_merge(self.__state, sync_data)
            # if 'tags' in sync_data:
            #     self.__acumulado['tags'] = list(set(self.__acumulado['tags']) | set(sync_data['tags']))
            # if 'tags_removed' in sync_data:
            #     self.__acumulado['tags'] = list(set(self.__acumulado['tags']) - set(sync_data['tags_removed']))
            # if 'categories' in sync_data:
            #     self.__acumulado['categories'].update(sync_data['categories'])
            # if 'categories_removed' in sync_data:
            #     self.__acumulado['categories'] = {cname:cval for cname, cval in self.__acumulado['categories'].items() if cname not in sync_data['categories_removed']}
            for thash in torrents_removed:
                self.__state['torrents'].pop(thash, None)

        self.__rid = sync_data.rid

    def login(self):
        try:
            self.auth_log_in()
        except qbittorrentapi.LoginFailed as e:
            raise

    def add_tags(self, hashes, tag):
        self.torrent_tags.add_tags(tag, hashes)

    def remove_tags(self, hashes, tags):
        self.torrent_tags.remove_tags(tags, hashes)

    # @property
    def torrent_files(self, thash):
        # Si es un archivo único, devuelve su ruta
        torrent = self.__state.get('torrents', {}).get(thash)
        content_path = torrent.get('content_path', '')
        # FIXME: no aplica translation path, por lo que nunca existe si vamos a buscarlo al disco.
        if is_file(content_path):
            return {content_path}

        filelist = set()
        files = self.torrents_files(thash)
        for file in files:
            # WARNING windows necesita normalizacion o uniria el path con el filename mediante /
            filelist.add(os.path.join(torrent.get('save_path'), file.name))
        return filelist

    def delete_tags(self, tags):
        self.torrent_tags.delete_tags(tags)

    def force_start(self, hashes):
        self.torrents.set_force_start(hashes)

    def resume_torrents(self, hashes):
        self.torrents.resume(hashes)

    def enable_tmm(self, hashes):
        self.torrents.set_auto_management(hashes)

    def sharelimit(self, hashes, limits):
        limit = {
            'torrent_hashes': hashes,
            'ratio_limit': limits['ratio'] if limits['ratio'] is not None else -2,
            'seeding_time_limit': limits['time'] if limits['time'] is not None else -2,
            'inactive_seeding_time_limit': -2
        }
        self.torrents.set_share_limits(**limit)

    def uploadlimit(self, hashes, limit):
        self.torrents_set_upload_limit(limit*1024, hashes)

# =================================================================

    # def get_torrents(self):
    #     return self.client.torrents_info()

    def get_trackers(self, thash):
        return self.torrents.trackers(thash)

    def start(self, thashes):
        return self.torrents_start(thashes)
