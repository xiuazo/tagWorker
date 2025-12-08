import qbittorrentapi
from dotenv import load_dotenv
import json
import os
import logging
from logging.handlers import TimedRotatingFileHandler

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

def get_clients():
    clients = {}

    # Obtiene y parsea el JSON
    defined_clients = json.loads(os.getenv("QBIT_CLIENTS", "[]"))

    for c in defined_clients:
        name = c.get('name')
        client = qbittorrentapi.Client(host=c['url'], username=c['user'], password=c['pass'])
        try:
            client.auth_log_in()
            clients[name] = client
            logger.info(f"✅ Conectado a instancia {name} ({c['url']})")
        except qbittorrentapi.LoginFailed as e:
                logger.warning(f"⚠️ Falló el login de {name}: {e}")
        except Exception as e:
            logger.error(f"❌ Error al conectar con {name} ({c['url']}): {e}")
        finally:
            return client
    return clients


def normalize_path(path):
    return os.path.normpath(path)

def translate_path(qbit_path):
    if QBITTORRENT_ROOTFOLDER and qbit_path.startswith(QBITTORRENT_ROOTFOLDER):
        relative_path = os.path.relpath(qbit_path, QBITTORRENT_ROOTFOLDER)
        return normalize_path(os.path.join(ROOTDIR, relative_path))
    return normalize_path(qbit_path)

def check_torrent_errors(torrent):
    errored = NOERROR

    if torrent.progress != 1: return NOERROR
    files = torrent.files
    for file in files:
        # Omitir archivos que no fueron seleccionados para descarga
        if file.priority == 0:
            continue

        qbit_file_path = normalize_path(os.path.join(torrent.save_path, file.name))
        real_file_path = translate_path(qbit_file_path)

        if not os.path.isfile(real_file_path):
            logger.info(f"Missing files: {torrent.name}")
            errored = ERROR_MISSING
            break
        elif os.path.getsize(real_file_path) != file.size:
            logger.info(f"Size missmatch: {torrent.name}")
            errored = ERROR_SIZE
            break

    return errored

if __name__ == "__main__":
    qbt_client = get_clients()
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

    logger.info(f"Torrents con errores: {len(errored_hashes)}. Pausados: {len(pauselist)}")
