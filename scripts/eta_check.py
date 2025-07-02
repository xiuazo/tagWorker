import qbittorrentapi

from dotenv import load_dotenv
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

AUTO_PAUSE = True
AUTO_RESUME = True

os.environ['QBITTORRENTAPI_HOST'] = os.getenv('QBITTORRENT_URL')
os.environ['QBITTORRENTAPI_USERNAME'] = os.getenv('QBITTORRENT_USERNAME')
os.environ['QBITTORRENTAPI_PASSWORD'] = os.getenv('QBITTORRENT_PASSWORD')

def completed(torrent):
    maxtime = torrent.max_seeding_time * 60 # API dice que en segundos. falso. devuelve minutos
    return maxtime >= 0 and maxtime < torrent.seeding_time

if __name__ == "__main__":
    with qbittorrentapi.Client() as qbt_client:
        torrents = qbt_client.torrents_info()

        pause, resume = list(), list()
        for t in torrents:
            paused = t.state == 'pausedUP'
            if completed(t):
                if not paused and t.state != 'forcedUP':
                    pause.append(t)
            elif paused:
                    resume.append(t)

        print('Should be paused:\n' + '-'*40)
        if pause:
            for t in pause:
                print(f"{t['name']} ({t.tracker[8:20]}..) is beyond his sharelimits")
            if AUTO_PAUSE:
                qbt_client.torrents_stop({t['hash'] for t in pause})
        print('\nShould be active:\n' + '-'*40)
        if resume:
            for t in resume:
                print(f"{t['name']} ({t.tracker[8:20]}..) not reached sharelimit")
            if AUTO_RESUME:
                pass
                qbt_client.torrents_start({t['hash'] for t in resume})
