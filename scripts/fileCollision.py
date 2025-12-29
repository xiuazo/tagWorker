import os
import json
from dotenv import load_dotenv
import utils

# Configuración
TAG_NAME = "💥"  # Nombre de la etiqueta para torrents con conflictos

script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path, override=True)


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

    return {k: duplicates[k] for k in sorted(duplicates)}


def main():
    qbt_client = utils.init_clients(json.loads(os.getenv("QBIT_CLIENTS", "[]")), single = True)

    torrents = qbt_client.torrents_info()
    duplicates = find_duplicate_files(torrents)

    if duplicates:
        logger.info("Se encontraron torrents duplicados que apuntan al mismo archivo:")
        hashes_to_tag = []
        for full_path, torrent_list in duplicates.items():
            logger.info(f"- Archivo: {full_path}")
            for torrent in torrent_list:
                print(f"  - {torrent.name}")
                hashes_to_tag.append(torrent["hash"])

        if hashes_to_tag:
            qbt_client.torrents_add_tags(TAG_NAME, hashes_to_tag)
            # tag_torrents(cookies, hashes_to_tag)
    else:
        logger.info("No se encontraron torrents duplicados.")


if __name__ == "__main__":
    logger = utils.setup_logger("fileCollision")
    main()
