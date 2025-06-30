import os
import requests
from urllib.parse import urljoin
from dotenv import load_dotenv

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)

# Configuración
QB_URL = os.getenv('QBITTORRENT_URL')
USERNAME = os.getenv('QBITTORRENT_USERNAME')
PASSWORD = os.getenv('QBITTORRENT_PASSWORD')

TAG_NAME = "@COLLISION"  # Nombre de la etiqueta para torrents con conflictos

def login_to_qbittorrent():
    """Inicia sesión en la API de qBittorrent y devuelve la cookie de sesión."""
    login_url = urljoin(QB_URL, "api/v2/auth/login")
    data = {
        "username": USERNAME,
        "password": PASSWORD
    }
    response = requests.post(login_url, data=data)
    if response.status_code == 200 and response.text == "Ok.":
        return response.cookies
    else:
        raise Exception("No se pudo iniciar sesión en qBittorrent. Verifica las credenciales y la URL.")

def get_torrents(cookies):
    """Obtiene la lista de torrents desde qBittorrent."""
    torrents_url = urljoin(QB_URL, "api/v2/torrents/info")
    response = requests.get(torrents_url, cookies=cookies)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception("No se pudo obtener la lista de torrents.")

def tag_torrents(cookies, hashes):
    """Asigna una etiqueta a múltiples torrents por sus hashes."""
    tag_url = urljoin(QB_URL, "api/v2/torrents/removeTags")
    requests.post(tag_url, data={'hashes':'all', 'tags': TAG_NAME}, cookies=cookies)
    tag_url = urljoin(QB_URL, "api/v2/torrents/addTags")
    data = {
        "hashes": '|'.join(hashes),
        "tags": TAG_NAME
    }
    response = requests.post(tag_url, data=data, cookies=cookies)
    if response.status_code != 200:
        raise Exception(f"No se pudo asignar la etiqueta a los torrents con hashes: {', '.join(hashes)}.")

def find_duplicate_files(torrents):
    """Encuentra torrents que apuntan al mismo archivo en el disco duro."""
    file_paths = {}
    duplicates = {}

    for torrent in torrents:
        # Extraemos la ruta completa del archivo o carpeta del torrent
        save_path = torrent.get("save_path", "")
        if not save_path.endswith("/") and not save_path.endswith("\\"):
            save_path += "/"
        name = torrent.get("name", "")

        # Ruta completa del archivo/carpeta
        full_path = save_path + name

        if full_path in file_paths:
            if full_path not in duplicates:
                duplicates[full_path] = [file_paths[full_path]]
            duplicates[full_path].append(torrent)
        else:
            file_paths[full_path] = torrent

    # Ordenar duplicados por clave alfabética
    return {k: duplicates[k] for k in sorted(duplicates)}

def main():
    try:
        # Borrar la terminal
        # os.system("cls" if os.name == "nt" else "clear")

        # Iniciar sesión
        cookies = login_to_qbittorrent()

        # Obtener torrents
        torrents = get_torrents(cookies)

        # Buscar duplicados
        duplicates = find_duplicate_files(torrents)

        # Imprimir resultados y etiquetar torrents
        if duplicates:
            print("Se encontraron torrents duplicados que apuntan al mismo archivo:")
            hashes_to_tag = []
            for full_path, torrent_list in duplicates.items():
                print(f"- Archivo: {full_path}")
                for torrent in torrent_list:
                    print(f"  - {torrent['name']}")
                    hashes_to_tag.append(torrent["hash"])

            # Etiquetar todos los torrents duplicados en una única llamada
            if hashes_to_tag:
                tag_torrents(cookies, hashes_to_tag)
        else:
            print("No se encontraron torrents duplicados.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
