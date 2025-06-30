from collections import defaultdict
import os
import requests
from dotenv import load_dotenv

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

QBIT_URL = os.getenv('QBITTORRENT_URL')
QBIT_USER = os.getenv('QBITTORRENT_USERNAME')
QBIT_PASS = os.getenv('QBITTORRENT_PASSWORD')

# Configuration variables
ROOTDIR = os.getenv('TORRENTS_PATH') # ruta al torrentdir real en el disco, completa
QBIT_ROOTFOLDER = os.getenv('TRANSLATED_TORRENTS_PATH') # ruta al torrentdir tal cual la ve qbit

TORRENT_CATEGORY = "xseed"
XSEEDFOLDER = '.linkDir'
ORPHANFOLDER = '.orphaned_data'
CROSS_SEED_TAG = "xs"
PREFIX_TAG = "xs."
POSTFIX_TAG = ""

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

def normalize_path(path):
    return os.path.normpath(path)

def translate_path(qbit_path):
    if QBIT_ROOTFOLDER and qbit_path.startswith(QBIT_ROOTFOLDER):
        relative_path = os.path.relpath(qbit_path, QBIT_ROOTFOLDER)
        return normalize_path(os.path.join(ROOTDIR, relative_path))
    return normalize_path(qbit_path)

def get_top_level_folder(relative_path):
    parts = normalize_path(relative_path).split(os.sep)
    return parts[0] if parts else "Unknown"

def qbit_login(session):
    login_url = f"{QBIT_URL}/api/v2/auth/login"
    login_data = {
        'username': QBIT_USER,
        'password': QBIT_PASS
    }

    response = session.post(login_url, data=login_data)
    if response.status_code != 200 or response.text != 'Ok.':
        raise ConnectionError("Failed to log in to qBittorrent. Check your credentials.")

def qbit_logout(session):
    logout_url = f"{QBIT_URL}/api/v2/auth/logout"
    session.post(logout_url)

def get_torrents(session, category):
    torrents_url = f"{QBIT_URL}/api/v2/torrents/info"
    params = {'category': category}

    response = session.get(torrents_url, params=params)
    if response.status_code != 200:
        raise ConnectionError("Failed to fetch torrents. Check your API URL and category.")

    return response.json()

def get_torrent_files(session, torrent_hash):
    files_url = f"{QBIT_URL}/api/v2/torrents/files"
    response = session.get(files_url, params={'hash': torrent_hash})

    if response.status_code != 200:
        raise ConnectionError(f"Failed to fetch files for torrent with hash '{torrent_hash}'.")

    return response.json()

def process_torrents(session, torrents, inode_dict):
    tag_queue = defaultdict(set)

    sorted_torrents = sorted(torrents, key=lambda x: x['name'])
    for torrent in sorted_torrents:
        torrent_name = torrent.get('name', 'Unknown')
        torrent_hash = torrent.get('hash', '')
        torrent_taglist = torrent.get('tags').split(', ')

        try:
            files = get_torrent_files(session, torrent_hash)
            hardlink_folders = set()

            for file in files:
                qbit_file_path = normalize_path(os.path.join(torrent['save_path'], file['name']))
                real_file_path = translate_path(qbit_file_path)

                try:
                    inode = os.stat(real_file_path).st_ino
                    hardlinks = inode_dict.get(inode, [])
                    for hardlink in hardlinks:
                        hardlink_relative_path = os.path.relpath(hardlink, ROOTDIR)
                        top_level_folder = get_top_level_folder(hardlink_relative_path)
                        hardlink_folders.add(top_level_folder)

                except FileNotFoundError:
                    print(f" - {real_file_path} (File not found): ")

            hardlink_folders.discard(XSEEDFOLDER)
            hardlink_folders.discard(ORPHANFOLDER)
            if hardlink_folders:
                for folder in hardlink_folders:
                    if tag_name(folder) not in torrent_taglist or CROSS_SEED_TAG not in torrent_taglist:
                        tag_queue[folder].add(torrent_hash)
                if len(hardlink_folders) > 1:
                    print(f"WARNING: Torrent {torrent_name} links to {len(hardlink_folders)} folders: {', '.join(hardlink_folders)}")
            else:
                print(f"Torrent: {torrent_name} only in {XSEEDFOLDER} folder")

        except ConnectionError as e:
            print(f"Error processing torrent '{torrent_name}': {e}")

    return tag_queue

def tag_name(folder):
    return f"{PREFIX_TAG}{folder}{POSTFIX_TAG}"

def apply_tags(session, tag_queue):
    total = 0
    for tag, hashes in tag_queue.items():
        tag_url = f"{QBIT_URL}/api/v2/torrents/addTags"
        tag = tag_name(tag)
        tag_data = {
            'hashes': '|'.join(hashes),
            'tags': f"{tag},{CROSS_SEED_TAG}"
        }
        tag_response = session.post(tag_url, data=tag_data)
        if tag_response.status_code == 200:
            count = len(hashes)
            print(f"Tagged {count} torrents with '{tag}'.")
            total += count
        else:
            print(f"Failed to tag torrents '{tag}'.")
    print(f'Tagged {total} torrents.')

def main():
    if not all([QBIT_URL, QBIT_USER, QBIT_PASS, QBIT_ROOTFOLDER]):
        print("Please ensure all required environment variables are set in the .env file.")
        return

    try:
        inode_dict = build_inode_dict(ROOTDIR)
        session = requests.Session()

        qbit_login(session)
        torrents = get_torrents(session, TORRENT_CATEGORY)

        if not torrents:
            print(f"No torrents found in category '{TORRENT_CATEGORY}'.")
        else:
            tag_queue = process_torrents(session, torrents, inode_dict)
            apply_tags(session, tag_queue)

        qbit_logout(session)

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
