import os
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from urllib.parse import urlparse
from dotenv import load_dotenv
import qbittorrentapi
from collections import defaultdict, namedtuple

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

# ---------------- LOGGER ----------------
def setup_logger():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, "logs")
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

    logger = logging.getLogger("huno")
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
    return clients

def human_readable_size(size_in_bytes):
    """Convierte un tamaño en bytes a una cadena en formato humano (KiB, MiB, GiB, etc.)."""
    if size_in_bytes < 1024:
        return f"{size_in_bytes} B"
    elif size_in_bytes < 1024**2:
        return f"{size_in_bytes / 1024:.2f} KiB"
    elif size_in_bytes < 1024**3:
        return f"{size_in_bytes / 1024**2:.2f} MiB"
    elif size_in_bytes < 1024**4:
        return f"{size_in_bytes / 1024**3:.2f} GiB"
    elif size_in_bytes < 1024**5:
        return f"{size_in_bytes / 1024**4:.2f} TiB"
    else:
        return f"{size_in_bytes / 1024**5:.2f} PiB"

TrackerStats = namedtuple("TrackerStats", ["size", "count"])
def sum_seedsizes(torrent_list):
    uniquehashes = set()
    trackers = defaultdict(lambda: TrackerStats(0,0))

    for torrent in torrent_list:
        if not torrent.tracker or torrent.hash in uniquehashes or torrent.progress != 1:
            continue
        uniquehashes.add(torrent.hash)
        tracker_name = urlparse(torrent.tracker).hostname
        current = trackers[tracker_name]
        trackers[tracker_name] = TrackerStats(
            size = current.size + torrent.size,
            count = current.count + 1
        )
    return trackers

def print_tracker_sizes(stats):
    sorted_stats = dict(sorted(stats.items(), key=lambda item: item[1].size, reverse=True))

    for name, tracker in sorted_stats.items():
        print(f"{name} ({tracker.count}): {human_readable_size(tracker.size)}")

def main():
    allt = []
    clients = get_clients()
    try:
        for client in clients.values():
            allt += client.torrents_info()
        stats = sum_seedsizes(allt)
        print_tracker_sizes(stats)
    except Exception as e:
        print(f'{e}')

if __name__ == "__main__":
    main()
