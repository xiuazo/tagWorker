import requests
from dotenv import load_dotenv
import os

load_dotenv()

# CONFIG
ROOTDIR = os.getenv('TORRENTS_PATH') # ruta al torrentdir real en el disco, completa
QBITTORRENT_ROOTFOLDER = os.getenv('TRANSLATED_TORRENTS_PATH') # ruta al torrentdir tal cual la ve qbit
ERRORED_TAG = "@ERRORED"
AUTOPAUSE_MISSING = True
AUTOPAUSE_SIZE_MISSMATCH = False
# END CONFIG

QB_URL = os.getenv('QBITTORRENT_URL')
QB_USER = os.getenv('QBITTORRENT_USERNAME')
QB_PASSWORD = os.getenv('QBITTORRENT_PASSWORD')

NOERROR = 0
ERROR_MISSING = 1
ERROR_SIZE = 2

def normalize_path(path):
    return os.path.normpath(path)

def translate_path(qbit_path):
    if QBITTORRENT_ROOTFOLDER and qbit_path.startswith(QBITTORRENT_ROOTFOLDER):
        relative_path = os.path.relpath(qbit_path, QBITTORRENT_ROOTFOLDER)
        return normalize_path(os.path.join(ROOTDIR, relative_path))
    return normalize_path(qbit_path)

def get_torrents(session):
    response = session.get(f'{QB_URL}/api/v2/torrents/info')
    if response.status_code != 200:
        raise Exception("No se pudo obtener la lista de torrents")
    return response.json()

def get_torrent_files(session, thash):
    response = session.get(f'{QB_URL}/api/v2/torrents/files', params={'hash': thash})
    if response.status_code != 200:
        raise Exception(f"No se pudo obtener la lista de archivos para {thash}")
    return response.json()

def check_torrent_errors(session, torrent):
    errored = NOERROR

    files = get_torrent_files(session, torrent['hash'])
    for file in files:
        # Omitir archivos que no fueron seleccionados para descarga
        if file['priority'] == 0:
            continue

        qbit_file_path = normalize_path(os.path.join(torrent['save_path'], file['name']))
        real_file_path = translate_path(qbit_file_path)

        if not os.path.isfile(real_file_path):
            errored = ERROR_MISSING
            break
        elif os.path.getsize(real_file_path) != file['size']:
            errored = ERROR_SIZE
            break

    return errored

def tag_torrents(session, torrents, tag):
    if torrents: # empty and tag
        response = session.post(f"{QB_URL}/api/v2/torrents/removeTags", data={"hashes": 'all', "tags": tag})
        hashes = "|".join(torrents)
        response = session.post(f"{QB_URL}/api/v2/torrents/addTags", data={"hashes": hashes, "tags": tag})
        if response.status_code != 200:
            raise Exception("Error al etiquetar torrents")
    else: # destroy tag
        response = session.post(f"{QB_URL}/api/v2/torrents/deleteTags", data={"tags": tag})

def qbit_login():
    session = requests.Session()
    login_data = {'username': QB_USER, 'password': QB_PASSWORD}
    response = session.post(f'{QB_URL}/api/v2/auth/login', data=login_data)

    if response.status_code != 200:
        raise Exception("No se pudo iniciar sesión en qBittorrent")
    return session

def pause_torrents(session, hashes):
    if not hashes:
        return
    response = session.post(f"{QB_URL}/api/v2/torrents/pause", data={"hashes": '|'.join(hashes)})
    if response.status_code != 200:
        raise Exception("Error al pausar")

if __name__ == "__main__":
    session = qbit_login()
    torrents = get_torrents(session)

    errored_hashes = set()
    pauselist = set()
    for torrent in torrents:
        result = check_torrent_errors(session, torrent)
        if result != NOERROR:
            errored_hashes.add(torrent['hash'])
            if (
                (result == ERROR_MISSING and AUTOPAUSE_MISSING)
                or (result == ERROR_SIZE and AUTOPAUSE_SIZE_MISSMATCH)
                ):
                pauselist.add(torrent['hash'])

    tag_torrents(session, errored_hashes, ERRORED_TAG)
    pause_torrents(session, pauselist)
    print(f"Torrents con errores: {len(errored_hashes)}. Pausados: {len(pauselist)}")
