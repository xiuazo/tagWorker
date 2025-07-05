import os
import time
from collections import defaultdict
from .logger import logger

def is_file(content_path):
    if os.path.isdir(content_path):
        return False
    if os.path.isfile(content_path):
        return True
    return None

def translate_path(fullpath, translation_table):
    path = fullpath
    for original, translated in translation_table.items():
        if fullpath.startswith(original):
            path = translated + fullpath[len(original):]
            break
    return os.path.normpath(path)

def move_to_dir(root_path, orphaned_path, file):
    if file.startswith(root_path):
        rel_path = file[len(root_path):]
        new_path = os.path.join(orphaned_path, rel_path.strip('\\').strip('/'))
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            os.rename(file, new_path)
            os.utime(new_path, (time.time(), time.time()))
        except Exception as e:
            logger.error(f'Error: {e}')
    else:
        logger.info(f"Path for {file} not in {root_path}")

def build_inode_map(path):
    inode_map = defaultdict(int)

    for dirpath, _, filenames in os.walk(path):
        for name in filenames:
            fullpath = os.path.join(dirpath, name)
            try:
                stat_path = os.stat(fullpath)
                inode = stat_path.st_ino
                inode_map[inode] += 1
            except FileNotFoundError:
                pass
    return inode_map

def file_has_outer_links(path, inode_map):
    try:
        stat = os.stat(path)
        in_count = inode_map[stat.st_ino]
        return stat.st_nlink > in_count
    except FileNotFoundError:
        return False

def remove_empty_dirs(path, dryrun=True, iname=''):
    # $ find $ROOT_FOLDER -type d -empty -delete
    if not os.path.isdir(path):
        return

    for name in os.listdir(path):
        fullpath = os.path.join(path, name)
        if os.path.isdir(fullpath):
            remove_empty_dirs(fullpath, dryrun, iname)

    # Después de eliminar los posibles subdirectorios vacíos, comprobamos si el actual está vacío
    if not os.listdir(path):
        try:
            if not dryrun: os.rmdir(path)
            logger.info(f"{iname:<10} - Removed empty dir: {path}")
        except OSError as e:
            logger.warning(f"{iname:<10} - Error deleting {path}: {e}")
