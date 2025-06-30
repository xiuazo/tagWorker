import os
from urllib.parse import urlparse
from dotenv import load_dotenv
import qbittorrentapi
from collections import defaultdict, namedtuple

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

clients = [
  {"host": os.getenv("QBITTORRENT_URL"), "username": os.getenv("QBITTORRENT_USERNAME"), "password": os.getenv("QBITTORRENT_PASSWORD")},
  {"host": os.getenv("QBITTORRENT_HBD_URL"), "username": os.getenv("QBITTORRENT_HBD_USERNAME"), "password": os.getenv("QBITTORRENT_HBD_PASSWORD")},
  {"host": os.getenv("QBITTORRENT_DOCK_URL"), "username": os.getenv("QBITTORRENT_DOCK_USERNAME"), "password": os.getenv("QBITTORRENT_DOCK_PASSWORD")}
]

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
        if not torrent.tracker or torrent.hash in uniquehashes:
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
    try:
        for client_config in clients:
            if not all(client_config.values()):
                continue
            with qbittorrentapi.Client(**client_config) as qbit_client:
                allt += qbit_client.torrents_info()
        stats = sum_seedsizes(allt)
        print_tracker_sizes(stats)
    except Exception as e:
        print(f'{e}')

if __name__ == "__main__":
    main()
