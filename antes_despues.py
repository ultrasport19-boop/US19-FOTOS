"""
antes_despues.py - Compone las portadas nuevas (lienzo 1000x1000) en local y
arma una hoja «antes | después» para revisarlas antes de publicar.

  python antes_despues.py ID ID ...     (usa C:\\yupoo_fotos\\_portadas.json)
"""
import io
import json
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portadas  # noqa: E402

COPIA = r"C:\yupoo_fotos"
REPO_FOTOS = r"C:\yupoo_trabajo\US19-FOTOS\fotos"
SALIDA = r"C:\yupoo_trabajo\revision"
dec = json.load(open(os.path.join(COPIA, "_portadas.json"), encoding="utf-8"))
nombres = {}
try:
    for f in json.load(open(r"C:\yupoo_trabajo\fase0_inventario\notion_filas.json", encoding="utf-8")):
        nombres.setdefault(f["id"], f["prenda"])
except Exception:
    pass

ids = sys.argv[1:]
lado, pad, alto_txt = 300, 10, 36
hoja = Image.new("RGB", (2 * (lado + pad) + pad + 10, 30 + len(ids) * (lado + alto_txt + pad)), "white")
d = ImageDraw.Draw(hoja)
d.text((pad, 8), "ANTES (portada actual)            |            DESPUES (frente completo, lienzo 1000x1000)", fill=(0, 0, 0))
os.makedirs(os.path.join(SALIDA, "previa_v2"), exist_ok=True)
for i, aid in enumerate(ids):
    y = 30 + i * (lado + alto_txt + pad)
    viejo = os.path.join(REPO_FOTOS, aid + ".webp")
    if os.path.exists(viejo):
        with Image.open(viejo) as im:
            im = im.convert("RGB"); im.thumbnail((lado, lado))
            hoja.paste(im, (pad + (lado - im.size[0]) // 2, y + (lado - im.size[1]) // 2))
    x = dec[aid]
    ruta = os.path.join(COPIA, aid, x["archivo"])
    caja, margen, nota = portadas.caja_final(ruta, x.get("caja"))
    datos, prenda, q = portadas.componer(ruta, caja, margen=margen)
    print("%s  %s → %s  margen %.0f %%  (%s)" % (aid, x.get("caja"), caja, 100 * margen, nota))
    with open(os.path.join(SALIDA, "previa_v2", aid + "-v2.webp"), "wb") as f:
        f.write(datos)
    with Image.open(io.BytesIO(datos)) as im:
        im = im.convert("RGB"); im.thumbnail((lado, lado))
        hoja.paste(im, (2 * pad + lado + 10, y))
    d.rectangle([2 * pad + lado + 10, y, 2 * pad + 2 * lado + 10, y + lado], outline=(200, 200, 200))
    d.text((pad, y + lado + 4), "%s  %s" % (aid, nombres.get(aid, "")[:48]), fill=(0, 0, 0))
    d.text((pad, y + lado + 18), "nueva: %s (%s) · %d KB q%d · prenda %dx%d px" % (
        x["archivo"], x["tipo"], len(datos) // 1024, q, prenda[0], prenda[1]), fill=(0, 100, 0))
destino = os.path.join(SALIDA, "antes_despues.jpg")
hoja.save(destino, quality=88)
print(destino)
