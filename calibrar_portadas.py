"""Hojas de calibración: todas las fotos distintas de cada álbum, ordenadas
por la heurística, con el recuadro de la prenda y la portada actual marcada."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portadas  # noqa: E402

COPIA = r"C:\yupoo_fotos"
SALIDA = r"C:\yupoo_trabajo\revision\calibracion"
estado = json.load(open(os.path.join(COPIA, "_estado.json"), encoding="utf-8"))["albumes"]
for aid in sys.argv[1:]:
    top, todas = portadas.candidatas(os.path.join(COPIA, aid), n=3)
    actual = estado.get(aid, {}).get("portada")
    portadas.hoja("%s  (actual: %s)  — orden de la heurística; las 3 primeras son las candidatas" % (aid, actual),
                  todas, os.path.join(SALIDA, aid + ".jpg"), lado=200, marcar=actual)
    print("%s  actual=%s  únicas=%d  top3=%s" % (aid, actual, len(todas),
          " | ".join("%s %.0f%% b%d %s" % (f["archivo"], 100 * f["area"], f["bordes"], "ok" if f["valida"] else "x") for f in top)))
