import os
import sys
import portalocker
import hashlib
from .logger import logger

class LockAcquisitionError(Exception):
    pass

def config_hash(config_path):
    try:
        with open(config_path, 'rb') as f:
            data = f.read()
        return hashlib.sha256(data).hexdigest()[:16]
    except FileNotFoundError:
        logger.error(f"Error: archivo no encontrado: {config_path}")
        sys.exit(1)
    except PermissionError:
        logger.error(f"Sin permisos para leer: {config_path}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error inesperado al leer configuración: {e}")
        sys.exit(1)


def get_lockfile_path(config_path):
    config_key = config_hash(config_path)
    lockfile_name = f"tagWorker_{config_key}.lock"
    lock_dir = "/tmp" if os.name != "nt" else os.environ.get("TEMP", "C:\\Temp")
    return os.path.join(lock_dir, lockfile_name)

def acquire_lock(config_path):
    lockfile_path = get_lockfile_path(config_path)
    try:
        lock_file = open(lockfile_path, "w")
        portalocker.lock(lock_file, portalocker.LOCK_EX | portalocker.LOCK_NB)
        return lock_file
    except portalocker.exceptions.LockException:
        raise LockAcquisitionError(f"Ya hay otra instancia usando configuración equivalente: {config_path}")
