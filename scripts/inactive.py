import os
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlparse
import qbittorrentapi

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

max_allowed = 50

RED = "\033[91m"
RESET = "\033[0m"

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

    logger = logging.getLogger("inactive")
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


def main():
  clients = get_clients()
  tracker_dict = defaultdict(int)
  for qbit_client in clients.values():
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
    main()
