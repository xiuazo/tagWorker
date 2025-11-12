import os
import requests
import qbittorrentapi
import logging
import json
from logging.handlers import TimedRotatingFileHandler
from urllib.parse import urljoin
from dotenv import load_dotenv

# Configuración
TAG_NAME = "@COLLISION"  # Nombre de la etiqueta para torrents con conflictos


script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)


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
        finally:
            return client
    return clients


def find_duplicate_files(torrents):
    """Encuentra torrents que apuntan al mismo archivo en el disco duro."""
    file_paths = {}
    duplicates = {}

    for torrent in torrents:
        # Extraemos la ruta completa del archivo o carpeta del torrent
        save_path = torrent.get("save_path", "")
        if not save_path.endswith("/") and not save_path.endswith("\\"):
            save_path += "/"
        name = torrent.get("name", "")

        # Ruta completa del archivo/carpeta
        full_path = save_path + name

        if full_path in file_paths:
            if full_path not in duplicates:
                duplicates[full_path] = [file_paths[full_path]]
            duplicates[full_path].append(torrent)
        else:
            file_paths[full_path] = torrent

    # Ordenar duplicados por clave alfabética
    return {k: duplicates[k] for k in sorted(duplicates)}

def main():
    qbt_client = get_clients()

    torrents = qbt_client.torrents_info()
    duplicates = find_duplicate_files(torrents)

    if duplicates:
        print("Se encontraron torrents duplicados que apuntan al mismo archivo:")
        hashes_to_tag = []
        for full_path, torrent_list in duplicates.items():
            print(f"- Archivo: {full_path}")
            for torrent in torrent_list:
                print(f"  - {torrent.name}")
                hashes_to_tag.append(torrent["hash"])

        if hashes_to_tag:
            qbt_client.torrents_add_tags(TAG_NAME, hashes_to_tag)
            # tag_torrents(cookies, hashes_to_tag)
    else:
        print("No se encontraron torrents duplicados.")

if __name__ == "__main__":
    main()
