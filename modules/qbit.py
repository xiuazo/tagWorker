import os
import requests
import uuid
import qbittorrentapi

from modules.files import is_file

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
        self._uid = uuid.uuid4()
        self._url = url
        self._user = user
        self._pwd = pwd

        self._prev_status = {} # estado anterior
        self._changes = {} # diff
        self._version = 0
        self._full_update = False

        # estado anterior + cambios. usar getter self.status()
        self._status = {}

        self.client = qbittorrentapi.Client(host=url, username=user, password=pwd)

    @classmethod
    def torrents(cls, uid = ''):
        if uid:
            return cls.total_torrents.get(uid, {})
        return cls.total_torrents

    @classmethod
    def all_torrents_iterator(cls):
        for uid, data in cls.total_torrents.items():
            yield uid, data

    def store_torrents(self):
        qBit.total_torrents[self._uid] = self.torrents

    @property
    def torrents(self):
        return self._status.get('torrents', {})

    @property
    def url(self):
        return self._url

    @property
    def session(self):
        return self._session

    @property
    def changes(self):
        return self._changes

    @property
    def status(self):
        return self._status

    def sync(self, fullsync = False):
        sync_data = self.client.sync.maindata(0 if fullsync else self._version)

        self._version = sync_data.rid
        self._changes = sync_data
        self._full_update = sync_data.get("full_update")

        if self._full_update:
            self._status = sync_data
            self._prev_status = {}
        elif sync_data:
            self._prev_status = self._status

            # this would drags old and unexisting things...
            self._status = deep_merge(self._prev_status, sync_data)
            # ... if we don't clean
            if 'tags' in sync_data:
                self._status['tags'] = list(set(self._status['tags']) | set(sync_data['tags']))
            if 'tags_removed' in sync_data:
                self._status['tags'] = list(set(self._status['tags']) - set(sync_data['tags_removed']))
            if 'categories' in sync_data:
                self._status['categories'].update(sync_data['categories'])
            if 'categories_removed' in sync_data:
                self._status['categories'] = {cname:cval for cname, cval in self._status['categories'].items() if cname not in sync_data['categories_removed']}
            if 'torrents_removed' in sync_data:
                self._status['torrents'] = {th:tv for th, tv in self._status['torrents'].items() if th not in sync_data['torrents_removed']}

        self.store_torrents()

    def login(self):
        pass

    def logout(self):
        pass

    def add_tags(self, hashes, tag):
        self.client.torrent_tags.add_tags(tag, hashes)

    def remove_tags(self, hashes, tags):
        self.client.torrent_tags.remove_tags(tags, hashes)

    def get_torrent_files(self, thash):
        files = self.client.torrents.files(thash)

        # Si es un archivo único, devuelve su ruta
        torrent = self._status.get('torrents', {})[thash]
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

    def get_torrents(self):
        return self.client.torrents_info()

    def get_trackers(self, thash):
        return self.client.torrents.trackers(thash)
