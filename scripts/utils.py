import logging
import os
from logging.handlers import TimedRotatingFileHandler
from qbittorrentapi import Client, LoginFailed


def init_clients(config, single=False):
    clients = []
    for c in config:
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
        if single: return client
    return clients

def setup_logger(name: str):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, "..", "logs")  # → ../logs/
    log_dir = os.path.abspath(log_dir)              # Normaliza la ruta
    os.makedirs(log_dir, exist_ok=True)

    # script_name = os.path.splitext(os.path.basename(__file__))[0]  # → "blah"
    script_name = os.path.splitext(name)[0]  # → "blah"
    log_file = os.path.join(log_dir, f"{script_name}.log")

    formatter = logging.Formatter(
        fmt="[%(asctime)s UTC] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Rotación diaria, conserva 7 días
    file_handler = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    global logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.propagate = False

    return logger
