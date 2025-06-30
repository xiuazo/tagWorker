import qbittorrentapi
from dotenv import load_dotenv
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

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

def check_torrent_errors(torrent):
    errored = NOERROR

    files = torrent.files
    for file in files:
        # Omitir archivos que no fueron seleccionados para descarga
        if file.priority == 0:
            continue

        qbit_file_path = normalize_path(os.path.join(torrent.save_path, file.name))
        real_file_path = translate_path(qbit_file_path)

        if not os.path.isfile(real_file_path):
            errored = ERROR_MISSING
            break
        elif os.path.getsize(real_file_path) != file.size:
            errored = ERROR_SIZE
            break

    return errored

if __name__ == "__main__":
    conn_info = dict({
        'host': QB_URL,
        'username': QB_USER,
        'password': QB_PASSWORD
    })
    with qbittorrentapi.Client(**conn_info) as qbt_client:
        torrents = qbt_client.torrents_info()

        errored_hashes = set()
        pauselist = set()
        for torrent in torrents:
            result = check_torrent_errors(torrent)
            if result != NOERROR:
                errored_hashes.add(torrent.hash)
                if (
                    (result == ERROR_MISSING and AUTOPAUSE_MISSING)
                    or (result == ERROR_SIZE and AUTOPAUSE_SIZE_MISSMATCH)
                    ):
                    pauselist.add(torrent.hash)

        qbt_client.torrents_add_tags(ERRORED_TAG, errored_hashes)
        qbt_client.torrents_stop(pauselist)
    print(f"Torrents con errores: {len(errored_hashes)}. Pausados: {len(pauselist)}")
