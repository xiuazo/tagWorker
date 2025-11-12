import qbittorrentapi
import logging
from logging.handlers import TimedRotatingFileHandler
import json
from dotenv import load_dotenv
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

AUTO_PAUSE = True
AUTO_RESUME = True

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

def completed(torrent):
    maxtime = torrent.max_seeding_time * 60 # API dice que en segundos. falso. devuelve minutos
    return maxtime >= 0 and maxtime < torrent.seeding_time

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

if __name__ == "__main__":
    clients = get_clients()

    for qbt_client in clients.values(): #with qbittorrentapi.Client() as qbt_client:
        torrents = qbt_client.torrents_info()

        pause, resume = list(), list()
        for t in torrents:
            if t.progress != 100: continue # ignore incomplete torrents
            paused = t.state == 'pausedUP'
            if completed(t):
                if not paused and t.state not in ['forcedUP']:
                    pause.append(t)
            elif paused:
                    resume.append(t)

        logger.info("Should be paused:")
        if pause:
            for t in pause:
                logger.info(f"{t['name']} ({t.tracker[8:20]}..) is beyond his sharelimits")
            if AUTO_PAUSE:
                qbt_client.torrents_stop({t['hash'] for t in pause})
        logger.info("Should be active:")
        if resume:
            for t in resume:
                logger.info(f"{t['name']} ({t.tracker[8:20]}..) not reached sharelimit")
            if AUTO_RESUME:
                pass
                qbt_client.torrents_start({t['hash'] for t in resume})
