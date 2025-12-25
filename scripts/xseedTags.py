import os
import json
import sys
import logging

from pathlib import Path

from logging.handlers import TimedRotatingFileHandler

from qbittorrentapi import Client, LoginFailed
from collections import defaultdict, namedtuple
from dotenv import load_dotenv

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

# Configuration variables
ROOTDIR = Path(os.getenv('TORRENTS_PATH', "")).resolve() # ruta al torrentdir real en el disco, completa
QBIT_ROOTFOLDER = Path(os.getenv('TRANSLATED_TORRENTS_PATH', "")).resolve() # ruta al torrentdir tal cual la ve qbit

TORRENT_CATEGORY = os.getenv('XSEED_CATEGORY', "cross-seed-link")
XSEED_FOLDER = os.getenv('XSEED_LINKDIR', ".linkDir")
ORPHANFOLDER = os.getenv('ORPHANED_PATH', ".orphaned_data")
XSEED_TAG = os.getenv('XSEED_TAG', "cross-seed")
PREFIX_TAG = os.getenv('XSEED_TAG_PREFIX', "")
POSTFIX_TAG = os.getenv('XSEED_TAG_POSTFIX', ".cross-seed")
XS_ORPHAN_TAG = os.getenv('XSEED_TAG_ORPHAN', f"@{XSEED_FOLDER}-only")

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

    logger = logging.getLogger("xseedTags")
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Evitar duplicados
    logger.propagate = False

    return logger

logger = setup_logger()


def init_clients(config):
    name = config.get('name')
    client = Client(host=config['url'], username=config['user'], password=config['pass'])
    try:
        client.auth_log_in()
        logger.info(f"✅ Conectado a instancia {name} ({config['url']})")
    except LoginFailed as e:
        logger.warning(f"⚠️ Falló el login de {name}: {e}")
    except Exception as e:
        logger.error(f"❌ Error al conectar con {name} ({config['url']}): {e}")
    finally:
        return client


def build_inode_dict(rootdir: Path):
    inode_dict = {}
    for path in rootdir.rglob('*'):  # recorre recursivamente
        if path.is_file():
            try:
                inode = path.stat().st_ino
                inode_dict.setdefault(inode, []).append(path)
            except FileNotFoundError:
                continue
    return inode_dict


def translate_path(qbit_path: str) -> Path:
    qbit = Path(qbit_path)

    try:
        relative = qbit.relative_to(QBIT_ROOTFOLDER)
        return (ROOTDIR / relative).resolve()
    except ValueError:
        return qbit.resolve()


def get_top_level_folder(relative_path: Path | str) -> str:
    p = Path(relative_path)
    if not p.parts:
        raise ValueError("Invalid or empty relative path.")
    return p.parts[0]


def process_torrents(torrents, inode_dict):
    simpleT = namedtuple('simpleT', ['name', 'hash'])
    tag_queue = defaultdict(set)
    xseed_only = set()
    for torrent in torrents:
        simple = simpleT(torrent.name, torrent.hash)
        if torrent.progress != 1: continue
        try:
            hardlink_folders = set()
            for file in torrent.files:
                qbit_path = Path(torrent.save_path) / file.name
                real_path = translate_path(qbit_path)
                try:
                    inode = real_path.stat().st_ino
                    for hardlink in inode_dict.get(inode, []):
                        hardlink_path = Path(hardlink)
                        hardlink_relative = hardlink_path.relative_to(ROOTDIR)
                        top_folder = get_top_level_folder(hardlink_relative)
                        hardlink_folders.add(top_folder)
                except FileNotFoundError:
                    logger.warning(f" - {real_path} (File not found)")
                except ValueError as e:
                    logger.warning(f" - Skipped invalid path: {hardlink_relative} ({e})")

            hardlink_folders.discard(XSEED_FOLDER)
            hardlink_folders.discard(ORPHANFOLDER)

            if not hardlink_folders:
                xseed_only.add(simple)
                continue

            for folder in hardlink_folders:
                existing_tags = set(torrent.tags.split(", "))
                if tag_name(folder) not in torrent.tags or XSEED_TAG not in existing_tags:
                    tag_queue[folder].add(simple)
            if len(hardlink_folders) > 1:
                logger.warning(f"WARNING: Torrent {torrent.name} links to {len(hardlink_folders)} folders: {', '.join(hardlink_folders)}")

        except ConnectionError as e:
            logger.warning(f"Error processing torrent '{torrent.name}': {e}")

    return tag_queue, xseed_only

def tag_name(folder):
    return f"{PREFIX_TAG}{folder}{POSTFIX_TAG}"


def apply_tags(session, tag_queue):
    total = 0
    for tag, simpleset in tag_queue.items():
        session.torrents_add_tags({tag_name(tag), XSEED_TAG}, {t.hash for t in simpleset})
        count = len(simpleset)
        logger.info(f"Tagged {count} torrents '{tag}'")
        total += count
    logger.info(f'Tagged {total} torrents')


def main():
    qbt_client = init_clients(json.loads(os.getenv("QBIT_CLIENTS", "[]"))[0])
    torrents = qbt_client.torrents_info(category=TORRENT_CATEGORY)

    if not torrents:
        logger.info(f"No torrents found in category '{TORRENT_CATEGORY}'.")
    else:
        inode_dict = build_inode_dict(ROOTDIR)
        tag_queue, xseed_only = process_torrents(torrents, inode_dict)
        apply_tags(qbt_client, tag_queue)

        qbt_client.torrents_delete_tags(XS_ORPHAN_TAG)
        if xseed_only:
            qbt_client.torrents_add_tags({XS_ORPHAN_TAG}, {t.hash for t in xseed_only})
            announced = set()
            for t in xseed_only:
                if t.name not in announced: logger.info(f"Torrent {t.name} only in {XSEED_FOLDER} folder")
                announced.add(t.name)


if __name__ == "__main__":
    main()
