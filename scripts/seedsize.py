import os
from urllib.parse import urlparse
from dotenv import load_dotenv
import qbittorrentapi
from collections import defaultdict

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

def sum_seedsizes(torrent_list):
    uniquehashes = set()
    trackers = defaultdict(float)
    tracker_count = defaultdict(int)

    for torrent in torrent_list:
        if not torrent.tracker or torrent.hash in uniquehashes:
            continue
        uniquehashes.add(torrent.hash)
        tracker_name = urlparse(torrent.tracker).hostname
        trackers[tracker_name] += torrent.size
        tracker_count[tracker_name] += 1
    return trackers, tracker_count

def print_tracker_sizes(trackers, count):
    sorted_trackers = sorted(trackers.items(), key=lambda item: item[1], reverse=True)

    for tracker, size in sorted_trackers:
        print(f"{tracker} ({count[tracker]}): {human_readable_size(size)}")

def main():
    allt = []
    try:
        for client_config in clients:
            if not all(client_config.values()):
                continue
            with qbittorrentapi.Client(**client_config) as qbit_client:
                allt += qbit_client.torrents_info()
        trackersize, trackertorrentcount = sum_seedsizes(allt)
        print_tracker_sizes(trackersize, trackertorrentcount)
    except Exception as e:
        print(f'{e}')

if __name__ == "__main__":
    main()
