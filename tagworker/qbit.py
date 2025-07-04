import os
import uuid
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

class qBit:
    total_torrents = {}

    def __init__(self, url, user, pwd):
        self.__client = qbittorrentapi.Client(host=url, username=user, password=pwd)
        self.__uid = uuid.uuid4()

        self.__sync_data = None
        self.__acumulado = {}

    @classmethod
    def all_torrents_iterator(self):
        for uid, data in self.total_torrents.items():
            yield uid, data

    @classmethod
    def store_torrents(self, obj):
        self.total_torrents[obj.id] = obj.torrents

    @property
    def id(self):
        return self.__uid

    @property
    def client(self):
        return self.__client

    @property
    def torrents(self):
        return self.__acumulado.get('torrents', {})

    @property
    def sync_data(self):
        return self.__sync_data

    @property
    def status(self):
        return self.__acumulado

    def sync(self, fullsync = False):
        if fullsync: self.client.sync.maindata.reset_rid()
        sync_data = self.client.sync.maindata.delta()

        self.__sync_data = sync_data

        if sync_data.get("full_update"):
            self.__acumulado = sync_data
        elif sync_data:
            # this would drags old and unexisting things...
            self.__acumulado = deep_merge(self.__acumulado, sync_data)
            # ... if we don't clean. but we don't care
            # if 'tags' in sync_data:
            #     self.__acumulado['tags'] = list(set(self.__acumulado['tags']) | set(sync_data['tags']))
            # if 'tags_removed' in sync_data:
            #     self.__acumulado['tags'] = list(set(self.__acumulado['tags']) - set(sync_data['tags_removed']))
            # if 'categories' in sync_data:
            #     self.__acumulado['categories'].update(sync_data['categories'])
            # if 'categories_removed' in sync_data:
            #     self.__acumulado['categories'] = {cname:cval for cname, cval in self.__acumulado['categories'].items() if cname not in sync_data['categories_removed']}
            if 'torrents_removed' in sync_data:
                self.__acumulado['torrents'] = {th:tv for th, tv in self.__acumulado['torrents'].items() if th not in sync_data['torrents_removed']}
        __class__.store_torrents(self)

    def login(self):
        try:
            self.client.auth_log_in()
        except qbittorrentapi.LoginFailed as e:
            raise

    def logout(self):
        self.client.auth_log_out()

    def add_tags(self, hashes, tag):
        self.client.torrent_tags.add_tags(tag, hashes)

    def remove_tags(self, hashes, tags):
        self.client.torrent_tags.remove_tags(tags, hashes)

    # @property
    def torrent_files(self, thash):
        files = self.client.torrents.files(thash)

        # Si es un archivo único, devuelve su ruta
        torrent = self.__acumulado.get('torrents', {})[thash]
        content_path = torrent.content_path
        if is_file(content_path):
            return {content_path}

        filelist = set()
        for file in files:
            # WARNING windows necesita normalizacion o uniria el path con el filename mediante /
            filelist.add(os.path.join(torrent.save_path, file.name))
        return filelist

    def delete_tags(self, tags):
        self.client.torrent_tags.delete_tags(tags)

    def force_start(self, hashes):
        self.client.torrents.set_force_start(hashes)

    def resume_torrents(self, hashes):
        self.client.torrents.resume(hashes)

    def enable_tmm(self, hashes):
        self.client.torrents.set_auto_management(hashes)

    def sharelimit(self, hashes, limits):
        limit = {
            'torrent_hashes': hashes,
            'ratio_limit': limits['ratio'] if limits['ratio'] is not None else -2,
            'seeding_time_limit': limits['time'] if limits['time'] is not None else -2,
            'inactive_seeding_time_limit': -2
        }
        self.client.torrents.set_share_limits(**limit)

    def uploadlimit(self, hashes, limit):
        self.client.torrents_set_upload_limit(limit*1024, hashes)

# =================================================================

    # def get_torrents(self):
    #     return self.client.torrents_info()

    def get_trackers(self, thash):
        return self.client.torrents.trackers(thash)
