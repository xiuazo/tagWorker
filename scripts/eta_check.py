import qbittorrentapi

from dotenv import load_dotenv
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

AUTO_PAUSE = False
AUTO_RESUME = False

QB_URL = os.getenv('QBITTORRENT_URL')
QB_USER = os.getenv('QBITTORRENT_USERNAME')
QB_PASSWORD = os.getenv('QBITTORRENT_PASSWORD')

def completed(torrent):
    maxtime = torrent['max_seeding_time'] * 60 # API dice que en segundos. falso. devuelve minutos
    return maxtime >= 0 and maxtime < t['seeding_time']

if __name__ == "__main__":
    conn_info = dict({
        'host': QB_URL,
        'username': QB_USER,
        'password': QB_PASSWORD
    })
    with qbittorrentapi.Client(**conn_info) as qbt_client:
        torrents = qbt_client.torrents_info()

        pause, resume = set(), set()
        for t in torrents:
            paused = t.state == 'pausedUP'
            if completed(t):
                if not paused and t.state != 'forcedUP':
                    # print(f"Warning: {t['name']} is beyond his sharelimits")
                    pause.add(t.hash)
            elif paused:
                    # print(f"Warning: {t['name']} stopped and not reached sharelimit")
                    resume.add(t.hash)

        print('Should pause\n' + '-'*60)
        if pause:
            print(pause)
            if AUTO_PAUSE:
                qbt_client.torrents_stop(pause)
        print('Should resume\n' + '-'*60)
        if resume:
            print(resume)
            if AUTO_RESUME:
                qbt_client.torrents_start(resume)
