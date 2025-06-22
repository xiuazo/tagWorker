
import os
import bencodepy

# Configuración
carpeta_fastresume = "/home/dockeruser/docker/qbittorrent/qBittorrent/BT_backup"
ruta_antigua = "/downloads/"
ruta_nueva = "/data/torrents/"

claves = set()
# Recorrer archivos .fastresume
for nombre_archivo in os.listdir(carpeta_fastresume):
    if not nombre_archivo.endswith(".fastresume"):
        continue

    ruta_archivo = os.path.join(carpeta_fastresume, nombre_archivo)

    with open(ruta_archivo, "rb") as f:
        try:
            contenido = bencodepy.decode(f.read())
        except Exception as e:
            print(f"Error leyendo {nombre_archivo}: {e}")
            continue

    cambiado = False

    for k in contenido.keys():
        if b"save" in k:
            claves.add(contenido[k])

    # Buscar y reemplazar en todas las claves que sean rutas (cadenas que contengan la ruta antigua)
    for clave in contenido:
        valor = contenido[clave]
        if isinstance(valor, bytes) and ruta_antigua.encode() in valor:
            valor_str = valor.decode('utf-8')
            valor_nuevo = valor_str.replace(ruta_antigua, ruta_nueva)
            contenido[clave] = valor_nuevo.encode('utf-8')
            print(f"[{nombre_archivo}] {clave.decode()}:")
            print(f"   {valor_str}")
            print(f"→  {valor_nuevo}")
            cambiado = True

    if cambiado:
    #     # Hacer backup
    #     os.rename(ruta_archivo, ruta_archivo + ".bak")

        # Escribir archivo actualizado
        with open(ruta_archivo, "wb") as f:
            f.write(bencodepy.encode(contenido))

# print(sorted(claves))
