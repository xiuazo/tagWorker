import os
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlparse
import qbittorrentapi

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

clients = [
  {"host": os.getenv("QBITTORRENT_URL"), "username": os.getenv("QBITTORRENT_USERNAME"), "password": os.getenv("QBITTORRENT_PASSWORD")},
  {"host": os.getenv("QBITTORRENT_HBD_URL"), "username": os.getenv("QBITTORRENT_HBD_USERNAME"), "password": os.getenv("QBITTORRENT_HBD_PASSWORD")},
  {"host": os.getenv("QBITTORRENT_DOCK_URL"), "username": os.getenv("QBITTORRENT_DOCK_USERNAME"), "password": os.getenv("QBITTORRENT_DOCK_PASSWORD")}
]
max_allowed = 50

RED = "\033[91m"
RESET = "\033[0m"

def main():
  tracker_dict = defaultdict(int)

  for client_config in clients:
    if not all(client_config.values()):
        continue
    with qbittorrentapi.Client(**client_config) as qbit_client:
      torrents = qbit_client.torrents_info()

    for t in torrents:
      if not t.tracker: continue
      tracker = urlparse(t.tracker).hostname
      last_added = tracker_dict[tracker]
      if t.added_on > last_added:
          tracker_dict[tracker] = t.added_on

  for key, val in sorted(tracker_dict.items()):
    last_time = datetime.fromtimestamp(val).strftime('%d/%m/%y')
    diferencia = timedelta(seconds=datetime.now().timestamp() - val).days

    print(f"{(RED if diferencia > max_allowed else '')}{key}: last torrent added on {last_time} ({diferencia} days ago){RESET}")


if __name__ == "__main__":
    main()
