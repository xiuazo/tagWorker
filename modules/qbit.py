import os
import requests
import uuid

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

# TODO borrar del status los torrents/categorias/tags que se eliminan
# https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)#get-main-data
class qBit:
    total_torrents = {}

    def __init__(self, url, user, pwd, commands):
        self._uid = uuid.uuid4()
        self._url = url
        self._user = user
        self._pwd = pwd
        self._commands = commands
        self._session = None

        self._prev_status = {} # estado anterior
        self._changes = {} # diff
        self._version = 0
        self._full_update = False
        # self._full_update_time = 0

        # estado anterior + cambios. usar getter self.status()
        self._status = {}

    # @classmethod
    # def torrents(cls, uid = ''):
    #     if uid:
    #         return cls.total_torrents.get(uid, {})
    #     return cls.total_torrents

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
        url = f'{self._url}/api/v2/sync/maindata?rid={0 if fullsync else self._version}'
        try:
            response = self._session.get(url)
            response.raise_for_status()
        except Exception as e:
            raise e

        response = response.json()

        self._version = response['rid']
        self._changes = response
        self._full_update = response.get('full_update',False)

        if self._full_update:
            self._status = response
            self._prev_status = {}
        elif response:
            self._prev_status = self._status

            # this would drags old and unexisting things...
            self._status = deep_merge(self._prev_status, response)
            # ... if we don't clean
            if 'tags' in response:
                self._status['tags'] = list(set(self._status['tags']) | set(response['tags']))
            if 'tags_removed' in response:
                # self._status['tags'] = [tag for tag in self._status['tags'] if tag not in response['tags_removed']]
                self._status['tags'] = list(set(self._status['tags']) - set(response['tags_removed']))
            if 'categories' in response:
                self._status['categories'].update(response['categories'])
            if 'categories_removed' in response:
                self._status['categories'] = {cname:cval for cname, cval in self._status['categories'].items() if cname not in response['categories_removed']}
            if 'torrents_removed' in response:
                self._status['torrents'] = {th:tv for th, tv in self._status['torrents'].items() if th not in response['torrents_removed']}

        self.store_torrents()

    def login(self):
        url = f'{self._url}/api/v2/auth/login'
        data = {
            "username": self._user,
            "password": self._pwd
        }
        session = requests.Session()
        self._session = session

        try:
            response = session.post(url, data=data)
            if response.ok and response.text == "Ok.":
                return session
        except Exception as e:
            raise e

    def logout(self):
        url = f'{self._url}/api/v2/auth/logout'
        response = self._session.post(url)
        if response.ok and response.status_code == 200:
            return
        raise Exception("Error logging out with qBittorrent")

    def add_tags(self, hashes, tag):
        url = f"{self._url}/api/v2/torrents/addTags"
        data = {
            "hashes": "|".join(hashes),
            "tags": tag
        }
        response = self.session.post(url, data=data)
        response.raise_for_status()

    def remove_tags(self, hashes, tags):
        url = f"{self._url}/api/v2/torrents/removeTags"
        if isinstance(hashes, str): hashes = [hashes]
        if isinstance(tags, str): tags = [tags]
        data = {
            "hashes": "|".join(hashes),
            "tags": ",".join(tags)
        }
        response = self._session.post(url, data=data)
        response.raise_for_status()

    def get_torrent_files(self, thash):
        # Si es un archivo único, devuelve su ruta
        torrent = self._status.get('torrents', {})[thash]
        content_path = torrent['content_path']
        if is_file(content_path):
            return {content_path}
        # Si es múltiple, llama a la API para obtener la lista de archivos
        url = f'{self._url}/api/v2/torrents/files?hash={thash}'
        response = self._session.get(url)
        response.raise_for_status()
        filelist = set()
        for file in response.json():
            # WARNING windows necesita normalizacion o uniria el path con el filename mediante /
            filelist.add(os.path.join(torrent['save_path'], file['name']))
        return filelist

    def delete_tags(self, tags):
        url = f"{self._url}/api/v2/torrents/deleteTags"
        if isinstance(tags, str):
            tags = [tags]
        data = {
            "tags": ",".join(tags)
        }
        response = self._session.post(url, data=data)
        response.raise_for_status()

    def force_start(self, hashes):
        url = f'{self._url}/api/v2/torrents/setForceStart'
        data = {
            'value':"true",
            'hashes': "|".join(hashes)
        }
        response = self._session.post(url, data=data)
        response.raise_for_status()

    def resume_torrents(self, hashes):
        url = f'{self._url}/api/v2/torrents/resume'
        data = {
            'hashes': "|".join(hashes)
        }
        response = self._session.post(url, data=data)
        response.raise_for_status()

    def enable_tmm(self, torrents):
        data = {
            'hashes': "|".join(torrents),
            'enable': "true"
        }
        response = self._session.post(f'{self._url}/api/v2/torrents/setAutoManagement', data=data)
        response.raise_for_status()

    def sharelimit(self, hashes, limits):
        limits = {
            'hashes': "|".join(hashes),
            'ratioLimit': limits['ratio'] if limits['ratio'] is not None else -2,
            'seedingTimeLimit': limits['time'] if limits['time'] is not None else -2,
            'inactiveSeedingTimeLimit': -2
        }
        response = self._session.post(f'{self._url}/api/v2/torrents/setShareLimits', data=limits)
        response.raise_for_status()

    def uploadlimit(self, hashes, limit):
        data = {
            'hashes': "|".join(hashes),
            'limit': limit * 1024
        }
        response = self._session.post(f'{self._url}/api/v2/torrents/setUploadLimit', data=data)
        response.raise_for_status()

# =================================================================

    def get_torrents(self):
        url = f'{self._url}/api/v2/torrents/info'
        response = self._session.get(url)
        response.raise_for_status()
        return response.json()

    def get_trackers(self, thash):
        url = f'{self._url}/api/v2/torrents/trackers?hash={thash}'
        response = self._session.get(url)
        response.raise_for_status()
        return response.json()
