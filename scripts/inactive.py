import os
from urllib.parse import urlparse
from datetime import datetime, timedelta
from dotenv import load_dotenv

import qbittorrentapi

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

clients = [
  [os.getenv("QBITTORRENT_URL"), os.getenv("QBITTORRENT_USERNAME"), os.getenv("QBITTORRENT_PASSWORD")],
  [os.getenv("QBITTORRENT_HBD_URL"), os.getenv("QBITTORRENT_HBD_USERNAME"), os.getenv("QBITTORRENT_HBD_PASSWORD")],
  [os.getenv("QBITTORRENT_DOCK_URL"), os.getenv("QBITTORRENT_DOCK_USERNAME"), os.getenv("QBITTORRENT_DOCK_PASSWORD")]
]
max_allowed = 50

RED = "\033[91m"
RESET = "\033[0m"

def main():
  tracker_dict = {}

  for url, user, password in clients:
    qbit_client = qbittorrentapi.Client(host=url, username=user, password=password)
    try:
       qbit_client.auth_log_in()
    except qbittorrentapi.LoginFailed as e :
       print(e)

    torrents = qbit_client.torrents_info()

    for t in torrents:
      tracker = urlparse(t.tracker).hostname
      last = tracker_dict.get(tracker, 0)
      if not tracker:
#         print(f'{t.get("name")} has no tracker.')
         continue

      if last < t.added_on:
          tracker_dict[tracker] = t.added_on

  for key in sorted(tracker_dict.keys()):
  # for key in tracker_dict.keys():
    host = key.split('.')[-2]
    # host = key
    val = tracker_dict[key]
    last_time = datetime.fromtimestamp(val).strftime('%d/%m/%y')
    diferencia = timedelta(seconds=datetime.now().timestamp() - val).days

    print(f"{(RED if diferencia > max_allowed else '')}{host}: last torrent added on {last_time} ({diferencia} days ago){RESET}")


if __name__ == "__main__":
    main()
