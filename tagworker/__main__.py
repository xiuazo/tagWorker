import sys
import platform
import time
import argparse
import threading
import signal
import schedule
from pytimeparse2 import parse
from .logger import logger
from .config import Config, GlobalConfig
from .worker import worker
from .locker import acquire_lock, LockAcquisitionError

CONFIG_FILE = 'config/config.yml'

stop_event = threading.Event()

def signal_handler(sig, frame):
    stop_event.set()

# Captura SIGTERM (systemd stop/restart) y SIGINT (Ctrl+C)
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

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


def main():
    signal.signal(signal.SIGINT, signal_handler)
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

    try:
        lock_file = acquire_lock(configfile)
    except LockAcquisitionError as e:
        logger.critical(f"{'APP':<10} - Ya hay otra instancia usando la misma configuración: {configfile}")
        sys.exit(1)

    logger.info(f"{'APP':<10} - Reading config file")
    app_config = Config(configfile)
    GlobalConfig.set(app_config)

    startup_msg()
    # inits
    workers = set()
    tag_interval = parse(GlobalConfig.get('app.tagging_schedule_interval', '15'))
    disk_interval = parse(GlobalConfig.get('app.disktasks_schedule_interval', '60m'))

    for name, client in GlobalConfig.get("clients").items():
        if client.enabled:
            workers.add( worker(name, client, tag_interval=tag_interval, disk_interval=disk_interval) )

    if singlerun:
        threads = []
        for w in workers:
            t = threading.Thread(target=w.run, kwargs={"singlerun": singlerun} )
            t.start()
            threads.append(t)

        for t in threads:
            t.join()  # Esperar a que todos terminen
    else:
        for w in workers:
            w.run(singlerun=False)
        try:
            while not stop_event.is_set():
                schedule.run_pending()
                time.sleep(1)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            logger.info(f"Shutdown requested...")
        # except KeyboardInterrupt:
        #     stop_event.set()

    for w in workers:
        try:
            logger.info(f"{w.name:<10} - Stopping...")
            w.logout()
        except Exception as e:
            logger.error(f"{w.name:<10}- Error stopping: {e}")


if __name__ == "__main__":
    main()
