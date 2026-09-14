"""
revisar_portadas.py - Paso 1 de la portada: prepara la hoja de revisión de cada álbum.

  python revisar_portadas.py ID ID ...        hojas de esos álbumes
  python revisar_portadas.py --por-revisar    los que el proceso dejó en «por_revisar»

Cada hoja (C:\\yupoo_trabajo\\revision\\<ID>.jpg) muestra en la PRIMERA FILA las 3
candidatas de la heurística (A, B, C) y debajo el resto de fotos distintas del
álbum, con una cuadrícula cada 10 %. La correspondencia letra → archivo queda en
C:\\yupoo_fotos\\_candidatas.json. La decisión (paso 2, con visión) se escribe en
C:\\yupoo_fotos\\_portadas.json:
  {"<ID>": {"archivo": "10.jpg", "tipo": "frontal" | "solo_espalda" | "dudosa",
            "caja": [x0, y0, x1, y1] | null, "motivo": "...", "version": 2}}
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portadas  # noqa: E402

COPIA = r"C:\yupoo_fotos"
REVISION = r"C:\yupoo_trabajo\revision"
CANDIDATAS = os.path.join(COPIA, "_candidatas.json")


def cargar(ruta, defecto):
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    return defecto


def guardar(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ruta)


def preparar(ids):
    estado = cargar(os.path.join(COPIA, "_estado.json"), {"albumes": {}})["albumes"]
    cands = cargar(CANDIDATAS, {})
    for aid in ids:
        carpeta = os.path.join(COPIA, aid)
        if not os.path.isdir(carpeta):
            print("%s: no está en la copia" % aid)
            continue
        top, todas = portadas.candidatas(carpeta, n=3)
        resto = [f for f in todas if f not in top]
        orden = top + resto
        actual = estado.get(aid, {}).get("portada")
        portadas.hoja("%s  A-C = candidatas de la heuristica (fila 1) · resto debajo · actual: %s" % (aid, actual or "-"),
                      orden, os.path.join(REVISION, aid + ".jpg"), lado=256, marcar=actual, cols=max(3, min(len(orden), 5)))
        cands[aid] = {chr(65 + i): {"archivo": f["archivo"], "caja": f.get("caja"), "valida": f["valida"],
                                    "motivo": f["motivo"], "lado": f["lado"]} for i, f in enumerate(orden)}
        print("%s: %d fotos distintas · candidatas %s" % (aid, len(orden),
              ", ".join("%s=%s" % (chr(65 + i), f["archivo"]) for i, f in enumerate(top))))
    guardar(CANDIDATAS, cands)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--por-revisar":
        est = cargar(os.path.join(COPIA, "_estado.json"), {"albumes": {}})["albumes"]
        args = sorted(a for a, v in est.items() if v.get("estado") == "por_revisar")
    preparar(args)
