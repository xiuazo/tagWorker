import os
import json
import logging
from dotenv import load_dotenv
from logging.handlers import TimedRotatingFileHandler
from qbittorrentapi import Client, TorrentState, LoginFailed

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

AUTO_PAUSE = True
AUTO_RESUME = True

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

    logger = logging.getLogger("eta_check")
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Evitar duplicados
    logger.propagate = False

    return logger

logger = setup_logger()


def is_completed(torrent):
    if torrent.max_seeding_time < 0:
        return False
    maxtime = torrent.max_seeding_time * 60 # API dice que en segundos. falso. devuelve minutos
    return torrent.seeding_time >= maxtime


def init_clients(client_definitions):
    clients = []
    for c in client_definitions:
        name = c.get('name')
        client = Client(host=c['url'], username=c['user'], password=c['pass'])
        try:
            client.auth_log_in()
            clients.append(client)
            logger.info(f"Conectado a {name} ({c['url']})")
        except LoginFailed as e:
            logger.warning(f"Falló el login a {name}: {e}")
        except Exception as e:
            logger.warning(f"Error al conectar a {name} ({c['url']}): {e}")
    return clients


def classify_torrents(torrents):
    pause_list, resume_list = list(), list()
    for torrent in torrents:
        if torrent.progress != 1: continue # ignore incomplete torrents
        is_paused = torrent.state_enum.is_paused

        if is_completed(torrent):
            if not is_paused and torrent.state_enum != TorrentState.FORCED_UPLOAD: # not in ['forcedUP']:
                pause_list.append(torrent)
        elif is_paused:
                resume_list.append(torrent)

    return pause_list, resume_list


def main():
    clients = init_clients(json.loads(os.getenv("QBIT_CLIENTS", "[]")))

    for qbt_client in clients:
        torrents = qbt_client.torrents_info()

        pause_list, resume_list = classify_torrents(torrents)

        if pause_list:
            logger.info("Torrents beyond their sharelimits:")
            for torrent in pause_list:
                logger.info(f"{torrent['name']} ({torrent.tracker[8:20]}..)")
            if AUTO_PAUSE:
                try:
                    qbt_client.torrents_pause({t['hash'] for t in pause_list})
                except Exception as e:
                    logger.warning(f"Error pausing torrents: {e}")

        if resume_list:
            logger.info("Torrents paused prematurely:")
            for torrent in resume_list:
                logger.info(f"{torrent['name']} ({torrent.tracker[8:20]}..)")
            if AUTO_RESUME:
                try:
                    qbt_client.torrents_resume({t['hash'] for t in resume_list})
                except Exception as e:
                    logger.warning(f"Error resuming torrents: {e}")


if __name__ == "__main__":
    main()
