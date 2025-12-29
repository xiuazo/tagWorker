import os
import json
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlparse
import utils

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

max_allowed = 50

RED = "\033[91m"
RESET = "\033[0m"

def main():
  clients = utils.init_clients(json.loads(os.getenv("QBIT_CLIENTS", "[]")))

  tracker_dict = defaultdict(int)
  for qbit_client in clients:
    torrents = qbit_client.torrents_info()

    for t in torrents:
      if not t.tracker: continue
      tracker = urlparse(t.tracker).hostname
      tracker_dict[tracker] = max(t.added_on, tracker_dict.get(tracker, 0))

  for key, val in sorted(tracker_dict.items()):
    last_time = datetime.fromtimestamp(val).strftime('%d/%m/%y')
    diferencia = timedelta(seconds=datetime.now().timestamp() - val).days

    if diferencia < max_allowed:
      logger.info(f"{key}: last torrent added on {last_time} ({diferencia} days ago)")
    else:
      logger.warning(f"{RED}{key}: last torrent added on {last_time} ({diferencia} days ago){RESET}")


if __name__ == "__main__":
    logger = utils.setup_logger("inactive")
    main()
