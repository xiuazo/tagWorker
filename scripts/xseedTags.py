import os
import json
import sys
import logging
from logging.handlers import TimedRotatingFileHandler

import qbittorrentapi
from collections import defaultdict
from dotenv import load_dotenv
script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

# Configuration variables
ROOTDIR = os.getenv('TORRENTS_PATH') # ruta al torrentdir real en el disco, completa
QBIT_ROOTFOLDER = os.getenv('TRANSLATED_TORRENTS_PATH') # ruta al torrentdir tal cual la ve qbit

TORRENT_CATEGORY = "xseed"
XSEEDFOLDER = '.linkDir'
ORPHANFOLDER = '.orphaned_data'
CROSS_SEED_TAG = "xs"
PREFIX_TAG = "xs."
POSTFIX_TAG = ""

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


def build_inode_dict(rootdir):
    inode_dict = {}
    for dirpath, _, filenames in os.walk(rootdir):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            try:
                inode = os.stat(filepath).st_ino
                if inode not in inode_dict:
                    inode_dict[inode] = []
                inode_dict[inode].append(filepath)
            except FileNotFoundError:
                continue
    return inode_dict

def translate_path(qbit_path):
    if QBIT_ROOTFOLDER and qbit_path.startswith(QBIT_ROOTFOLDER):
        relative_path = os.path.relpath(qbit_path, QBIT_ROOTFOLDER)
        return os.path.normpath(os.path.join(ROOTDIR, relative_path))
    return os.path.normpath(qbit_path)

def get_top_level_folder(relative_path):
    parts = os.path.normpath(relative_path).split(os.sep)
    if parts and parts[0]:
        return parts[0]
    raise ValueError("Invalid or empty relative path.")

def process_torrents(torrents, inode_dict):
    tag_queue = defaultdict(set)
    xseed_only = set()
    for torrent in torrents:
        if torrent.progress != 1: continue
        try:
            hardlink_folders = set()
            for file in torrent.files:
                qbit_path = os.path.normpath(os.path.join(torrent.save_path, file.name))
                real_path = translate_path(qbit_path)
                try:
                    inode = os.stat(real_path).st_ino
                    hardlinks = inode_dict.get(inode)
                    for hardlink in hardlinks:
                        hardlink_relative_path = os.path.relpath(hardlink, ROOTDIR)
                        top_level_folder = get_top_level_folder(hardlink_relative_path)
                        hardlink_folders.add(top_level_folder)
                except FileNotFoundError:
                    print(f" - {real_path} (File not found): ")
                except ValueError as e:
                    print(f" - Skipped invalid path: {hardlink_relative_path} ({e})")

            hardlink_folders.discard(XSEEDFOLDER)
            hardlink_folders.discard(ORPHANFOLDER)

            if not hardlink_folders:
                xseed_only.add(torrent.name)
                continue

            for folder in hardlink_folders:
                if tag_name(folder) not in torrent.tags or CROSS_SEED_TAG not in torrent.tags:
                    tag_queue[folder].add(torrent.hash)
            if len(hardlink_folders) > 1:
                print(f"WARNING: Torrent {torrent.name} links to {len(hardlink_folders)} folders: {', '.join(hardlink_folders)}")

        except ConnectionError as e:
            print(f"Error processing torrent '{torrent.name}': {e}")

    if xseed_only:
        for n in sorted(xseed_only):
            print(f"Torrent: {n} only in {XSEEDFOLDER} folder")

    return tag_queue

def tag_name(folder):
    return f"{PREFIX_TAG}{folder}{POSTFIX_TAG}"

def apply_tags(session, tag_queue):
    total = 0
    for tag, hashes in tag_queue.items():
        session.torrents_add_tags(tag_name(tag), hashes)
        count = len(hashes)
        print(f"Tagged {count} torrents '{tag}'")
        total += count
    print(f'Tagged {total} torrents')

def main():
    qbt_client = get_clients()
    torrents = qbt_client.torrents_info(category=TORRENT_CATEGORY)

    if not torrents:
        print(f"No torrents found in category '{TORRENT_CATEGORY}'.")
    else:
        inode_dict = build_inode_dict(ROOTDIR)
        tag_queue = process_torrents(torrents, inode_dict)
        apply_tags(qbt_client, tag_queue)


if __name__ == "__main__":
    main()
