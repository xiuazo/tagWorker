import json
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from logging.handlers import TimedRotatingFileHandler
import qbittorrentapi

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

# CONFIG
ROOTDIR = Path(os.getenv('TORRENTS_PATH', "")).resolve() # ruta al torrentdir real en el disco, completa
QBIT_ROOT = Path(os.getenv('TRANSLATED_TORRENTS_PATH', "")).resolve() # ruta al torrentdir tal cual la ve qbit
ERRORED_TAG = "@ERRORED"
AUTOPAUSE_MISSING = True
AUTOPAUSE_SIZE_MISSMATCH = False
# END CONFIG

NOERROR = 0
ERROR_MISSING = 1
ERROR_SIZE = 2

# ---------------- LOGGER ----------------
def setup_logger():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, "..", "logs")  # → ../logs/
    log_dir = os.path.abspath(log_dir)              # Normaliza la ruta
    os.makedirs(log_dir, exist_ok=True)

    script_name = os.path.splitext(os.path.basename(__file__))[0]  # → "blah"
    log_file = os.path.join(log_dir, f"{script_name}.log")

    formatter = logging.Formatter(
        fmt="[%(asctime)s UTC] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Rotación diaria, conserva 7 días
    file_handler = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger = logging.getLogger("torrent_health")
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Evitar duplicados
    logger.propagate = False

    return logger

logger = setup_logger()


def qbit_client_init(qb_config) -> qbittorrentapi.Client:
    try:
        client = qbittorrentapi.Client(host=qb_config.get('url'), username=qb_config.get('user'), password=qb_config.get('pass'))
        client.auth_log_in()
        logger.info(f"✅ Conectado a instancia {qb_config.get('name')} ({qb_config['url']})")
    except qbittorrentapi.LoginFailed as e:
        logger.warning(f"⚠️ Falló el login de {qb_config.get('name')}: {e}")
        raise e
    except Exception as e:
        logger.error(f"❌ Error al conectar con {qb_config.get('name')} ({qb_config['url']}): {e}")
        raise e

    return client


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
    qbt_client = qbit_client_init(
        json.loads(os.getenv("QBIT_CLIENTS", "[]"))[0]
    )
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
    main()
