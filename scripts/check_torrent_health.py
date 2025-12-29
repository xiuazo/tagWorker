import json
import os
from pathlib import Path
from dotenv import load_dotenv
import utils

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

# CONFIG
ROOTDIR = Path(os.getenv('TORRENTS_PATH', "")).resolve() # ruta al torrentdir real en el disco, completa
QBIT_ROOT = Path(os.getenv('TRANSLATED_TORRENTS_PATH', "")).resolve() # ruta al torrentdir tal cual la ve qbit
ERRORED_TAG = "☢️"
AUTOPAUSE_MISSING = True
AUTOPAUSE_SIZE_MISSMATCH = False
# END CONFIG

NOERROR = 0
ERROR_MISSING = 1
ERROR_SIZE = 2

def translate_path(qbit_path: str) -> Path:
    qbit = Path(qbit_path)

    try:
        relative = qbit.relative_to(QBIT_ROOT)
        return (ROOTDIR / relative).resolve()
    except ValueError:
        return qbit.resolve()


def check_torrent_status(torrent):
    if torrent.progress != 1: # ignore incomplete torrents
        return NOERROR

    for file in torrent.files:
        if file.priority == 0: # skip file download
            continue

        qbit_file_path = os.path.join(torrent.save_path, file.name)
        real_file_path = translate_path(qbit_file_path)

        if not real_file_path.is_file():
            logger.info(f"Missing files: {torrent.name}")
            return ERROR_MISSING

        stat = real_file_path.stat()

        if file.progress == 1.0 and stat.st_blocks == 0:
            logger.info(f"File not materialized on disk: {torrent.name}")
            return ERROR_SIZE

    return NOERROR


def main():
    qbt_client = utils.init_clients( json.loads(os.getenv("QBIT_CLIENTS", "[]")), single= True )
    torrents = qbt_client.torrents_info()

    errored_hashes = set()
    pauselist = set()
    for torrent in torrents:
        torrent_status = check_torrent_status(torrent)
        if torrent_status == NOERROR:
            continue
        errored_hashes.add(torrent.hash)
        if (
            (torrent_status == ERROR_MISSING and AUTOPAUSE_MISSING)
            or (torrent_status == ERROR_SIZE and AUTOPAUSE_SIZE_MISSMATCH)
            ):
            pauselist.add(torrent.hash)

    qbt_client.torrents_add_tags(ERRORED_TAG, errored_hashes)
    qbt_client.torrents_stop(pauselist)

    logger.info(f"Torrents con errores: {len(errored_hashes)}. Pausados: {len(pauselist)}")


if __name__ == "__main__":
    logger = utils.setup_logger("torrent_health")
    main()
