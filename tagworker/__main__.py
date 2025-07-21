import sys
import platform
import time
import argparse

from .logger import logger
from .config import Config, GlobalConfig
from .worker import worker
from .locker import acquire_lock, LockAcquisitionError

CONFIG_FILE = 'config/config.yml'

def print_banner(version="0.0.1"):
    # ANSI codes
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    FG_WHITE = "\033[37m"
    FG_YELLOW = "\033[33m"
    FG_CYAN = "\033[36m"
    FG_GREEN = "\033[32m"
    # Disable if not interactive terminal
    if not sys.stdout.isatty():
        RESET = BOLD = DIM = FG_WHITE = FG_YELLOW = FG_CYAN = FG_GREEN = ""

    banner = fr"""
   __             _       __           __
  / /_____ _____ | |     / /___  _____/ /_____  _____
 / __/ __ `/ __ `/ | /| / / __ \/ ___/ //_/ _ \/ ___/
/ /_/ /_/ / /_/ /| |/ |/ / /_/ / /  / ,< /  __/ /
\__/\__,_/\__, / |__/|__/\____/_/  /_/|_|\___/_/
         /____/

"""

    print(f"{FG_CYAN}{banner}{RESET}")
    print("-" * 72)
    print(f"{BOLD}Version         : {FG_GREEN}{version}{RESET}")
    print(f"{BOLD}License         : {FG_YELLOW}GNU General Public License v3.0{RESET}")
    print(f"{BOLD}                  {DIM}https://www.gnu.org/licenses/gpl-3.0.html{RESET}")
    print(f"{BOLD}Copyright       : {FG_CYAN}(C) 2025 xiu{RESET}")
    print(f"{BOLD}                  {FG_CYAN}https://github.com/xiuazo/tagWorker{RESET}")
    print(f"{BOLD}                  {FG_WHITE}This is free software. You may modify and")
    print(f"{BOLD}                  {FG_WHITE}redistribute it under the same license.{RESET}")
    print("-" * 72)

def startup_msg(config=None):
    config = GlobalConfig.get()

    print('')
    logger.info(f"Platform        : {platform.system()} {platform.release()}")
    logger.info(f"Python          : {platform.python_version()}")
    logger.info(f"qBit clients    : {len(config.clients)}")

    if config:
        tracker_details = len(config.tracker_details)
        logger.info(f"FullSync every  : {getattr(config.app, 'fullsync_interval', 'N/A')}")
        logger.info(f"Refresh interval: {getattr(config.app, 'tagging_schedule_interval', 'N/A')}")
        logger.info(f"Disk Schedule   : {getattr(config.app, 'disktasks_schedule_interval', 'N/A')}")
        logger.info(f"Scan Dupes      : {getattr(config.app.dupes, 'enabled', 'disabled')}")
        logger.info(f"Trackers        : {tracker_details}")
    print('')

def stop_instances(instances):
    for instance in instances:
        try:
            logger.info(f"{instance.name:<10} - Stopping...")
            instance.stop()
        except Exception as e:
            logger.error(f"{instance.name:<10}- Error stopping: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="Mantiene tu qBittorrent en orden"
    )
    parser.add_argument(
        "-s", "--singlerun",
        action="store_true",
        help="Ejecuta el script una sola vez"
    )
    parser.add_argument(
        "-c", "--config",
        type=str,
        default=CONFIG_FILE,
        help=f"Ruta al archivo de configuración (por defecto: {CONFIG_FILE})"
    )

    args = parser.parse_args()
    singlerun = args.singlerun
    configfile = args.config

    print_banner()
    logger.info(f"{'APP':<10} - Logger init")
    logger.info(f"{'APP':<10} - Reading config file")

    if not singlerun: # siendo singlerun permitimos que exista otra instancia ejecucion
        try:
            lock_file = acquire_lock(configfile)
        except LockAcquisitionError as e:
            logger.critical(f"{'APP':<10} - Ya hay otra instancia usando la misma configuración: {configfile}")
            sys.exit(1)

    app_config = Config(configfile)
    GlobalConfig.set(app_config)

    startup_msg()
    # inits
    instances = set()
    for name, client in GlobalConfig.get("clients").items():
        if not client.enabled:
            continue
        try:
            instance = worker(name, client)
            instance.run(singlerun)
            instances.add(instance)
        except Exception as e:
            logger.critical(f"{name:<10} - {e} {str(e)}")
            raise

    try:
        if not singlerun:
            while True:
                time.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        stop_instances(instances)


if __name__ == "__main__":
    main()
