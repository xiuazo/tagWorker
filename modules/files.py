import os
import time
from modules.logger import logger
from pytimeparse2 import parse

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
    inode_map = {}

    for dirpath, _, filenames in os.walk(path):
        for name in filenames:
            fullpath = os.path.join(dirpath, name)
            try:
                stat_path = os.stat(fullpath)
                inode = stat_path.st_ino

                if stat_path.st_nlink == 1:
                    continue
                if inode in inode_map:
                    inode_map[inode].append(fullpath)
                else:
                    inode_map[inode] = [fullpath]
            except FileNotFoundError:
                pass

    return inode_map

def verificar_hardlinks(target_file, inode_map):
    try:
        target_stat = os.stat(target_file)
        target_inode = target_stat.st_ino
        target_st_nlink = target_stat.st_nlink

        if target_inode in inode_map and len(inode_map[target_inode]) < target_st_nlink:
                return True
        return False

    except FileNotFoundError:
        return "File not found."

def remove_empty_dirs(path, instancename=''):
    if not os.path.isdir(path):
        return

    for name in os.listdir(path):
        fullpath = os.path.join(path, name)
        if os.path.isdir(fullpath):
            remove_empty_dirs(fullpath, instancename)

    # Después de eliminar los posibles subdirectorios vacíos, comprobamos si el actual está vacío
    if not os.listdir(path):
        try:
            # os.rmdir(path)
            logger.info(f'%-10s - Removed empty dir: {path}', instancename)
        except OSError as e:
            logger.warning(f'%-10s - Error deleting {path}: {e}', instancename)
