import os
import json
from dotenv import load_dotenv
from qbittorrentapi import TorrentState
import utils

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

AUTO_PAUSE = True
AUTO_RESUME = True

# ---------------- LOGGER ----------------


def is_completed(torrent):
    if torrent.max_seeding_time < 0:
        return False
    maxtime = torrent.max_seeding_time * 60 # API dice que en segundos. falso. devuelve minutos
    return torrent.seeding_time >= maxtime


def classify_torrents(torrents):
    pause_list, resume_list = list(), list()
    for torrent in torrents:
        if torrent.progress != 1: continue # ignore incomplete torrents
        is_paused = torrent.state_enum.is_paused

        if is_completed(torrent):
            if not is_paused and torrent.state_enum != TorrentState.FORCED_UPLOAD: # not in ['forcedUP']:
                pause_list.append(torrent)
        elif is_paused:
                resume_list.append(torrent)

    return pause_list, resume_list


def main():
    clients = utils.init_clients(json.loads(os.getenv("QBIT_CLIENTS", "[]")))

    for qbt_client in clients:
        torrents = qbt_client.torrents_info()

        pause_list, resume_list = classify_torrents(torrents)

        if pause_list:
            logger.info("Torrents beyond their sharelimits:")
            for torrent in pause_list:
                logger.info(f"{torrent['name']} ({torrent.tracker[8:20]}..)")
            if AUTO_PAUSE:
                try:
                    qbt_client.torrents_pause({t['hash'] for t in pause_list})
                except Exception as e:
                    logger.warning(f"Error pausing torrents: {e}")

        if resume_list:
            logger.info("Torrents paused prematurely:")
            for torrent in resume_list:
                logger.info(f"{torrent['name']} ({torrent.tracker[8:20]}..)")
            if AUTO_RESUME:
                try:
                    qbt_client.torrents_resume({t['hash'] for t in resume_list})
                except Exception as e:
                    logger.warning(f"Error resuming torrents: {e}")


if __name__ == "__main__":
    logger = utils.setup_logger("eta_check")
    main()
