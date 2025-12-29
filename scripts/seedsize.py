import os
import json
import humanize

from urllib.parse import urlparse
from dotenv import load_dotenv
from collections import defaultdict, namedtuple
import utils


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
        logger.info(f"{name} ({tracker.count}): {humanize.naturalsize(tracker[0], binary=True, format='%.2f')}")


def main():
    allt = []
    clients = utils.init_clients(json.loads(os.getenv("QBIT_CLIENTS", "[]")))
    try:
        for client in clients:
            allt += client.torrents_info()
        stats = sum_seedsizes(allt)
        print_tracker_sizes(stats)
    except Exception as e:
        print(f'{e}')


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    dotenv_path = os.path.join(script_dir, '.env')
    load_dotenv(dotenv_path, override=True)
    TrackerStats = namedtuple("TrackerStats", ["size", "count"])
    logger = utils.setup_logger("seedsize")
    main()
