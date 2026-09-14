#!/usr/bin/env python3
"""
subir_fotos.py - Portadas de Yupoo -> GitHub Pages -> Notion (tienda US19).

Se puede correr las veces que haga falta. En cada pasada:
  * toma solo carpetas ESTABLES (imagen legible, nada tocado en 2 min,
    mismo tamano en dos lecturas); lo demas queda «pendiente»;
  * salta lo hecho: el estado local y, sobre todo, las filas que en Notion
    ya tienen Foto (esa es la verdad final);
  * nunca toca el origen en OneDrive: copia a C:\\yupoo_fotos\\<AlbumID>.

Uso:
  python subir_fotos.py                     todo lo listo, en tandas de 200
  python subir_fotos.py --max 10            solo 10 albumes y para (piloto)
  python subir_fotos.py --solo ID,ID,...    solo esos albumes
  python subir_fotos.py --seco              no publica ni escribe en Notion

El token de Notion se lee de la variable de entorno NOTION_TOKEN y no se
escribe nunca en el log, en el estado ni en un commit.
"""
import argparse
import datetime as dt
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings

from PIL import Image, ImageOps

# Pillow avisa de paletas con transparencia al pasar a gris: no es un fallo.
warnings.filterwarnings("ignore", category=UserWarning, module="PIL")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portadas  # noqa: E402  (elige y compone la portada: camiseta completa de frente)

# ----------------------------------------------------------------- config
ORIGEN = r"C:\Users\diego\OneDrive\Escritorio\yupo\fotos"
COPIA = r"C:\yupoo_fotos"
ESTADO = os.path.join(COPIA, "_estado.json")
PORTADAS = os.path.join(COPIA, "_portadas.json")   # decisiones del paso 2 (con visión)
VERSION_PORTADA = 2                                # v2: camiseta completa de frente, lienzo 1000x1000
TRABAJO = r"C:\yupoo_trabajo"
REPO_DIR = os.path.join(TRABAJO, "US19-FOTOS")
RAMA_FOTOS = "gh-pages"
PAGES_BASE = "https://ultrasport19-boop.github.io/US19-FOTOS/"
NOTION_DB = "10f36430c43e43a19fddf64ef236ca68"
NOTION_VERSION = "2022-06-28"
PROP_ALBUM, PROP_FOTO, PROP_FOTO_URL = "Álbum ID", "Foto", "Foto URL"

LOTE = 200                  # albumes por tanda (un commit por tanda)
QUIETO_S = 120              # nada modificado en los ultimos 2 minutos
ESPERA_TAMANO_S = 5         # segunda lectura del tamano
TECHO_NOTION = 5 * 1024 * 1024
INTENTOS_MAX = 3
PAGES_ESPERA_MAX_S = 900    # lo que se espera a que GitHub Pages publique una tanda
NOTION_INTERVALO_S = 0.35   # ~3 peticiones por segundo
EXT_IMG = (".jpg", ".jpeg", ".png", ".webp", ".gif")
# atributos de Windows de un marcador «solo en la nube» de OneDrive
ATTR_NUBE = 0x00400000 | 0x00040000 | 0x00001000


# ----------------------------------------------------------------- log
class Log:
    def __init__(self, ruta):
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        self.f = open(ruta, "a", encoding="utf-8")
        self.ruta = ruta

    def __call__(self, *partes):
        linea = dt.datetime.now().strftime("%H:%M:%S") + "  " + " ".join(str(p) for p in partes)
        print(linea, flush=True)
        self.f.write(linea + "\n")
        self.f.flush()


def ahora_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


# ----------------------------------------------------------------- estado
def cargar_estado():
    if os.path.exists(ESTADO):
        with open(ESTADO, encoding="utf-8") as f:
            est = json.load(f)
        est.setdefault("albumes", {})
        return est
    return {"version": 1, "albumes": {}}


def guardar_estado(est):
    tmp = ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(est, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ESTADO)


def marcar(est, aid, estado, mensaje="", sumar_intento=False, guardar=True, **extra):
    e = est["albumes"].setdefault(aid, {"estado": "pendiente", "intentos": 0, "mensaje": ""})
    if sumar_intento:
        e["intentos"] = e.get("intentos", 0) + 1
        if e["intentos"] >= INTENTOS_MAX:
            estado = "error"
    e["estado"] = estado
    e["mensaje"] = mensaje
    e["actualizado"] = ahora_iso()
    e.update(extra)
    if guardar:
        guardar_estado(est)
    return e


# ----------------------------------------------------------------- Notion
class NotionError(Exception):
    def __init__(self, codigo, detalle):
        super().__init__("HTTP %s: %s" % (codigo, detalle))
        self.codigo = codigo


class Notion:
    URL = "https://api.notion.com"

    def __init__(self, token, log):
        self.token = token
        self.log = log
        self.ultima = 0.0
        self.peticiones = 0

    def req(self, metodo, ruta, cuerpo=None):
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        for intento in range(6):
            espera = NOTION_INTERVALO_S - (time.time() - self.ultima)
            if espera > 0:
                time.sleep(espera)
            self.ultima = time.time()
            self.peticiones += 1
            r = urllib.request.Request(self.URL + ruta, data=datos, method=metodo, headers={
                "Authorization": "Bearer " + self.token,
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            })
            try:
                with urllib.request.urlopen(r, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detalle = e.read().decode("utf-8", "replace")[:300]
                if e.code == 429 or e.code >= 500:
                    ra = e.headers.get("Retry-After")
                    pausa = min(float(ra) if ra else 2 ** intento, 60)
                    self.log("   Notion %s en %s %s: reintento en %.0f s" % (e.code, metodo, ruta.split("?")[0], pausa))
                    time.sleep(pausa)
                    continue
                raise NotionError(e.code, detalle)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                pausa = 2 ** intento
                self.log("   Notion sin respuesta (%s): reintento en %s s" % (type(e).__name__, pausa))
                time.sleep(pausa)
        raise NotionError(0, "sin respuesta tras 6 intentos")


def esquema(notion, log, seco):
    db = notion.req("GET", "/v1/databases/" + NOTION_DB)
    props = db["properties"]
    for nombre, tipo in ((PROP_ALBUM, "rich_text"), (PROP_FOTO, "files")):
        if nombre not in props or props[nombre]["type"] != tipo:
            raise SystemExit("La base no tiene «%s» de tipo %s. No sigo." % (nombre, tipo))
    if PROP_FOTO_URL in props:
        if props[PROP_FOTO_URL]["type"] != "url":
            raise SystemExit("«Foto URL» existe pero no es de tipo url. No sigo.")
    elif seco:
        log("«Foto URL» no existe; en modo seco no se crea.")
    else:
        notion.req("PATCH", "/v1/databases/" + NOTION_DB, {"properties": {PROP_FOTO_URL: {"url": {}}}})
        log("Columna «Foto URL» (url) creada en la base.")
        db = notion.req("GET", "/v1/databases/" + NOTION_DB)
        props = db["properties"]
    return {n: props[n]["id"] for n in (PROP_ALBUM, PROP_FOTO, PROP_FOTO_URL) if n in props}


def leer_filas(notion, ids_prop):
    """Todas las filas: [{pagina, album, fotos, foto_url}]."""
    qs = "&".join("filter_properties=" + urllib.parse.quote(pid, safe="%") for pid in ids_prop.values())
    filas, cursor = [], None
    while True:
        cuerpo = {"page_size": 100}
        if cursor:
            cuerpo["start_cursor"] = cursor
        r = notion.req("POST", "/v1/databases/%s/query?%s" % (NOTION_DB, qs), cuerpo)
        for p in r["results"]:
            pr = p.get("properties", {})
            album = "".join(t.get("plain_text", "") for t in pr.get(PROP_ALBUM, {}).get("rich_text", [])).strip()
            filas.append({
                "pagina": p["id"],
                "album": album,
                "fotos": len(pr.get(PROP_FOTO, {}).get("files", [])),
                "foto_url": (pr.get(PROP_FOTO_URL) or {}).get("url"),
            })
        if not r.get("has_more"):
            return filas
        cursor = r["next_cursor"]


def filas_de_volcado(ruta):
    """Solo para --seco sin token: filas del volcado de la fase 0."""
    with open(ruta, encoding="utf-8") as f:
        crudo = json.load(f)
    out = []
    for x in crudo:
        pid = x["url"].rstrip("/").split("/")[-1].split("-")[-1][-32:]
        out.append({"pagina": pid, "album": x["id"], "fotos": 0, "foto_url": None})
    return out


def subir_a_notion(notion, aid, url, paginas):
    """File Upload por URL externa + PATCH de Foto y Foto URL en cada fila."""
    tocadas = []
    for pid in paginas:
        fu = notion.req("POST", "/v1/file_uploads", {
            "mode": "external_url", "external_url": url, "filename": aid + ".webp"})
        estado = fu.get("status")
        for _ in range(40):
            if estado == "uploaded":
                break
            if estado in ("failed", "expired"):
                raise NotionError("upload", "la importación por URL quedó en «%s»" % estado)
            time.sleep(1.5)
            fu = notion.req("GET", "/v1/file_uploads/" + fu["id"])
            estado = fu.get("status")
        if estado != "uploaded":
            raise NotionError("upload", "la importación por URL no terminó (estado %s)" % estado)
        r = notion.req("PATCH", "/v1/pages/" + pid, {"properties": {
            PROP_FOTO: {"files": [{"type": "file_upload", "file_upload": {"id": fu["id"]}, "name": aid + ".webp"}]},
            PROP_FOTO_URL: {"url": url},
        }})
        if len(r.get("properties", {}).get(PROP_FOTO, {}).get("files", [])) < 1:
            raise NotionError("verificación", "Notion no devolvió la foto en la fila")
        tocadas.append(pid)
    return tocadas


# ----------------------------------------------------------------- carpetas
def resumen(ruta):
    """(n_archivos, bytes, mtime_max, hay_marcador_nube, imagenes_ordenadas)"""
    n = b = 0
    mt = 0.0
    nube = False
    imgs = []
    for e in os.scandir(ruta):
        if not e.is_file():
            continue
        st = e.stat()
        n += 1
        b += st.st_size
        mt = max(mt, st.st_mtime)
        if getattr(st, "st_file_attributes", 0) & ATTR_NUBE:
            nube = True
        if os.path.splitext(e.name)[1].lower() in EXT_IMG and st.st_size > 0:
            imgs.append(e.name)
    imgs.sort(key=lambda s: s.lower())
    return n, b, mt, nube, imgs


def estables(ids, log):
    """Regla de oro: 2 min quieta, mismo tamano en dos lecturas, sin marcadores."""
    primera = {}
    for aid in ids:
        try:
            primera[aid] = resumen(os.path.join(ORIGEN, aid))
        except OSError:
            pass
    time.sleep(ESPERA_TAMANO_S)
    listas, motivos = [], {}
    t = time.time()
    for aid, r1 in primera.items():
        try:
            r2 = resumen(os.path.join(ORIGEN, aid))
        except OSError as e:
            motivos[aid] = "no se pudo leer la carpeta (%s)" % e
            continue
        if not r2[4]:
            motivos[aid] = "sin imágenes todavía"
        elif r2[3]:
            motivos[aid] = "archivos solo en la nube (marcador de OneDrive)"
        elif (r1[0], r1[1]) != (r2[0], r2[1]):
            motivos[aid] = "el tamaño cambió entre dos lecturas (%s→%s bytes)" % (r1[1], r2[1])
        elif t - r2[2] < QUIETO_S:
            motivos[aid] = "modificada hace %d s (se espera %d)" % (t - r2[2], QUIETO_S)
        else:
            listas.append((aid, r2))
    return listas, motivos


def copiar(aid, r_origen):
    src, dst = os.path.join(ORIGEN, aid), os.path.join(COPIA, aid)
    os.makedirs(dst, exist_ok=True)
    for e in os.scandir(src):
        if not e.is_file():
            continue
        d = os.path.join(dst, e.name)
        if not os.path.exists(d) or os.path.getsize(d) != e.stat().st_size:
            shutil.copy2(e.path, d)
    r_copia = resumen(dst)
    if (r_copia[0], r_copia[1]) != (r_origen[0], r_origen[1]):
        raise RuntimeError("la copia no cuadra con el origen (%s/%s vs %s/%s)"
                           % (r_copia[0], r_copia[1], r_origen[0], r_origen[1]))
    return dst, r_copia[4]


def leer_imagen(ruta):
    """Abre de verdad (decodifica) y devuelve (ancho, alto)."""
    with Image.open(ruta) as im:
        im.load()
        return im.size


def escribir_si_cambia(destino, datos):
    """Escribe el WebP solo si cambió: así una pasada repetida no genera commit."""
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    if os.path.exists(destino):
        with open(destino, "rb") as f:
            if f.read() == datos:
                return False
    tmp = destino + ".tmp"
    with open(tmp, "wb") as f:
        f.write(datos)
    os.replace(tmp, destino)
    return True


# ----------------------------------------------------------------- GitHub
def git(*args, check=True):
    r = subprocess.run(["git", "-C", REPO_DIR] + list(args), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), (r.stderr or r.stdout).strip()[:300]))
    return r.stdout.strip()


def preparar_repo(log):
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        raise SystemExit("No está el repositorio de fotos en %s." % REPO_DIR)
    rama = git("rev-parse", "--abbrev-ref", "HEAD")
    if rama != RAMA_FOTOS:
        raise SystemExit("El repositorio de fotos está en la rama «%s», no en «%s»." % (rama, RAMA_FOTOS))
    git("pull", "--ff-only", "origin", RAMA_FOTOS, check=False)


def publicar(tanda_n, nombres, log):
    git("add", "--", "fotos")
    if not git("status", "--porcelain", "--", "fotos"):
        log("   GitHub: nada nuevo que subir (las portadas ya estaban publicadas)")
        return False
    git("commit", "-q", "-m", "fotos: tanda %d · %d portadas (%s)" % (tanda_n, len(nombres), ahora_iso()))
    for intento in range(3):
        r = subprocess.run(["git", "-C", REPO_DIR, "push", "-q", "origin", RAMA_FOTOS],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            log("   GitHub: commit y push de la tanda %d (%d portadas)" % (tanda_n, len(nombres)))
            return True
        log("   GitHub: push falló (%s); reintento" % r.stderr.strip()[:160])
        time.sleep(5 * (intento + 1))
    raise RuntimeError("no se pudo hacer push a GitHub")


def http_estado(url, metodo="HEAD"):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method=metodo), timeout=30) as r:
            return r.status, int(r.headers.get("Content-Length") or -1)
    except urllib.error.HTTPError as e:
        return e.code, -1
    except Exception:
        return 0, -1


def esperar_pages(urls_tam, log):
    """Espera a que GitHub Pages sirva cada URL con su tamaño. Devuelve las que responden 200."""
    pendientes = dict(urls_tam)
    listas = set()
    limite = time.time() + PAGES_ESPERA_MAX_S
    while pendientes and time.time() < limite:
        for url, tam in list(pendientes.items()):
            cod, largo = http_estado(url + "?v=%d" % time.time())   # sin caché del CDN
            if cod == 200 and largo in (tam, -1):
                cod2, _ = http_estado(url)                           # y la URL tal cual
                if cod2 == 200:
                    listas.add(url)
                    del pendientes[url]
        if pendientes:
            time.sleep(10)
    if pendientes:
        log("   GitHub Pages todavía no sirve %d portada(s) tras %d s: quedan pendientes"
            % (len(pendientes), PAGES_ESPERA_MAX_S))
    return listas


# ----------------------------------------------------------------- principal
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--solo", default="")
    ap.add_argument("--seco", action="store_true")
    ap.add_argument("--filas", default="", help="volcado local de filas (solo con --seco y sin token)")
    a = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    global ESTADO
    if a.seco:                       # el modo seco no toca el estado real
        ESTADO = os.path.join(COPIA, "_estado_seco.json")
    os.makedirs(COPIA, exist_ok=True)
    log = Log(os.path.join(TRABAJO, "logs", "subida_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S") + ".log"))
    log("=== Portadas Yupoo → Notion%s ===" % (" (MODO SECO: no publica ni escribe)" if a.seco else ""))
    est = cargar_estado()

    token = os.environ.get("NOTION_TOKEN", "").strip()
    notion = None
    if token:
        notion = Notion(token, log)
        ids_prop = esquema(notion, log, a.seco)
        filas = leer_filas(notion, ids_prop)
    elif a.seco and a.filas:
        log("Sin NOTION_TOKEN: uso el volcado local " + a.filas)
        filas = filas_de_volcado(a.filas)
    else:
        raise SystemExit("Falta la variable de entorno NOTION_TOKEN.")
    total_filas = len(filas)
    por_album = {}
    for f in filas:
        if f["album"]:
            por_album.setdefault(f["album"], []).append(f)
    con_foto_ini = sum(1 for f in filas if f["fotos"] > 0)
    log("Notion: %d filas · %d álbumes distintos · %d ya con foto" % (total_filas, len(por_album), con_foto_ini))

    if not a.seco:
        preparar_repo(log)

    carpetas = sorted(e.name for e in os.scandir(ORIGEN) if e.is_dir() and e.name.isdigit())
    sin_fila = [c for c in carpetas if c not in por_album]
    for c in sin_fila:
        if est["albumes"].get(c, {}).get("estado") != "sin_fila":
            marcar(est, c, "sin_fila", "no hay fila en Notion con ese Álbum ID", guardar=False)
    guardar_estado(est)
    decisiones = {}
    if os.path.exists(PORTADAS):
        with open(PORTADAS, encoding="utf-8") as f:
            decisiones = json.load(f)
    candidatos, ya_hechos, en_error, reparar = [], 0, 0, 0
    for c in carpetas:
        if c not in por_album:
            continue
        filas_c = por_album[c]
        falta = [f for f in filas_c if f["fotos"] == 0]
        e = est["albumes"].get(c, {})
        # Revisada = portada v2 puesta. Notion manda: si todas sus filas ya apuntan a un
        # «-v2.webp», se da por revisada aunque el estado local se haya perdido.
        v2_en_notion = bool(filas_c) and all((f["foto_url"] or "").endswith("-v%d.webp" % VERSION_PORTADA)
                                             for f in filas_c)
        revisada = e.get("portada_version") == VERSION_PORTADA or v2_en_notion
        if not falta and revisada:
            if e.get("estado") not in ("hecho", "portada_dudosa"):
                marcar(est, c, "hecho", "Notion ya tenía la portada v2", portada_version=VERSION_PORTADA, guardar=False)
            ya_hechos += 1
            continue
        if e.get("estado") == "portada_dudosa" and revisada:
            ya_hechos += 1                             # se dejó la foto actual a propósito
            continue
        if e.get("estado") == "error":
            en_error += 1
            continue
        if not falta:
            reparar += 1                               # tiene Foto, pero de la selección vieja
        candidatos.append(c)
    guardar_estado(est)
    if reparar:
        log("Filas con foto de la selección vieja (se revisan con la v2): %d álbum(es)" % reparar)
    if a.solo:
        pedidos = [x.strip() for x in a.solo.split(",") if x.strip()]
        candidatos = [c for c in pedidos if c in candidatos]
        log("Solo los pedidos: %d de %d están por hacer" % (len(candidatos), len(pedidos)))
    sin_carpeta = [aid for aid in por_album if aid not in set(carpetas)]
    log("Carpetas: %d · sin fila: %d · ya hechas: %d · en error: %d · por revisar: %d · álbumes de Notion aún sin carpeta: %d"
        % (len(carpetas), len(sin_fila), ya_hechos, en_error, len(candidatos), len(sin_carpeta)))

    listas, motivos = estables(candidatos, log)
    for aid, m in motivos.items():
        marcar(est, aid, "pendiente", m, guardar=False)
    guardar_estado(est)
    if motivos:
        log("Pendientes por descarga o inestables: %d (ej. %s: %s)"
            % (len(motivos), next(iter(motivos)), next(iter(motivos.values()))))
    if a.max:
        listas = listas[:a.max]
    log("Listas para procesar en esta pasada: %d" % len(listas))

    hechas, errores_pasada, tanda_n = [], [], 0
    por_revisar, dudosas, solo_espalda, ya_correctas, reemplazadas = [], [], [], [], []
    base_fotos = os.path.join(REPO_DIR if not a.seco else os.path.join(TRABAJO, "salida_seco"), "fotos")
    for i in range(0, len(listas), LOTE):
        tanda = listas[i:i + LOTE]
        tanda_n += 1
        log("--- Tanda %d: %d álbumes ---" % (tanda_n, len(tanda)))
        preparados = []          # dicts: aid, url, tam, paginas, archivo, tipo, caja, reemplaza
        for aid, r in tanda:
            try:
                dst, imgs = copiar(aid, r)
                dec = decisiones.get(aid)
                if not dec or dec.get("version") != VERSION_PORTADA:
                    marcar(est, aid, "por_revisar", "falta elegir la portada: paso 2 (mirar la hoja de revisión)", guardar=False)
                    por_revisar.append(aid)
                    continue
                tipo = dec.get("tipo", "frontal")
                e = est["albumes"].get(aid, {})
                if tipo == "dudosa":
                    marcar(est, aid, "portada_dudosa", dec.get("motivo", ""), portada_version=VERSION_PORTADA)
                    dudosas.append(aid)
                    log("   %s: portada DUDOSA → se deja la foto actual (%s)" % (aid, dec.get("motivo", "")))
                    continue
                archivo = dec["archivo"]
                ruta = os.path.join(dst, archivo)
                leer_imagen(ruta)                                    # que exista y se abra de verdad
                con_foto = [f for f in por_album[aid] if f["fotos"] > 0]
                if con_foto and len(con_foto) == len(por_album[aid]) and archivo == e.get("portada"):
                    marcar(est, aid, "hecho", "ya_correcta: la elegida es la que ya estaba", ya_correcta=True,
                           portada_version=VERSION_PORTADA, tipo=tipo)
                    ya_correctas.append(aid)
                    log("   %s: ya_correcta (%s): no se toca la fila" % (aid, archivo))
                    continue
                caja, margen, nota = portadas.caja_final(ruta, dec.get("caja"))
                datos, prenda, q = portadas.componer(ruta, caja, margen=margen)
                if len(datos) > TECHO_NOTION:
                    raise RuntimeError("el WebP pesa %d bytes, sobre el techo de 5 MiB" % len(datos))
                nombre = "%s-v%d.webp" % (aid, VERSION_PORTADA)
                escribir_si_cambia(os.path.join(base_fotos, nombre), datos)
                preparados.append({"aid": aid, "url": PAGES_BASE + "fotos/" + nombre, "tam": len(datos),
                                   "paginas": [f["pagina"] for f in por_album[aid]], "archivo": archivo,
                                   "tipo": tipo, "caja": caja, "reemplaza": bool(con_foto)})
                log("   %s: portada %s (%s) · %s · margen %d %% · prenda %dx%d en 1000x1000 · %d KB q%d · %d fila(s)%s"
                    % (aid, archivo, tipo, nota, round(100 * margen), prenda[0], prenda[1], len(datos) // 1024, q,
                       len(por_album[aid]), " · REEMPLAZA la foto actual" if con_foto else ""))
                log("      por qué: %s" % dec.get("motivo", "(sin motivo anotado)"))
            except Exception as e:
                ent = marcar(est, aid, "pendiente", "preparación: %s" % e, sumar_intento=True)
                if ent["estado"] == "error":
                    errores_pasada.append(aid)
                log("   %s: FALLO al preparar (%s) → %s" % (aid, e, ent["estado"]))
        guardar_estado(est)
        if a.seco:
            for p in preparados:
                marcar(est, p["aid"], "pendiente", "modo seco: preparada, sin publicar", portada_prevista=p["archivo"])
            log("   (modo seco: no se publica ni se escribe en Notion)")
            continue
        if not preparados:
            continue
        try:
            publicar(tanda_n, [p["aid"] for p in preparados], log)
        except Exception as e:
            log("   GitHub: %s → la tanda queda pendiente" % e)
            for p in preparados:
                marcar(est, p["aid"], "pendiente", "no se pudo publicar en GitHub: %s" % e)
            continue
        vivas = esperar_pages({p["url"]: p["tam"] for p in preparados}, log)
        for p in preparados:
            aid, url = p["aid"], p["url"]
            if url not in vivas:
                marcar(est, aid, "pendiente", "GitHub Pages aún no sirve la portada", url=url)
                continue
            try:
                tocadas = subir_a_notion(notion, aid, url, p["paginas"])   # Foto = [nueva]: reemplaza, no acumula
                marcar(est, aid, "hecho", "", url=url, paginas=tocadas, portada=p["archivo"], tipo=p["tipo"],
                       caja=p["caja"], bytes=p["tam"], portada_version=VERSION_PORTADA)
                hechas.append(aid)
                if p["reemplaza"]:
                    reemplazadas.append(aid)
                if p["tipo"] == "solo_espalda":
                    solo_espalda.append(aid)
                log("   %s: ✓ Notion%s · %s · páginas %s" % (aid, " (reemplazada)" if p["reemplaza"] else "", url, ", ".join(tocadas)))
            except Exception as e:
                ent = marcar(est, aid, "pendiente", "Notion: %s" % e, sumar_intento=True, url=url)
                if ent["estado"] == "error":
                    errores_pasada.append(aid)
                log("   %s: FALLO en Notion (%s) → %s (intento %d de %d)" % (aid, e, ent["estado"], ent["intentos"], INTENTOS_MAX))
        log("Avance: %d hechas en esta pasada · %d de %d listas revisadas" % (len(hechas), min(i + LOTE, len(listas)), len(listas)))

    # ------------------------------------------------------------- resumen
    con_foto = con_foto_ini
    if notion and not a.seco:
        try:
            con_foto = sum(1 for f in leer_filas(notion, esquema(notion, log, True)) if f["fotos"] > 0)
        except Exception as e:
            con_foto = con_foto_ini + sum(len(est["albumes"][h].get("paginas", [])) for h in hechas)
            log("(no pude recontar en Notion: %s)" % e)
    cuenta = {}
    for v in est["albumes"].values():
        cuenta[v["estado"]] = cuenta.get(v["estado"], 0) + 1
    log("=== RESUMEN DE LA PASADA ===")
    log("procesadas ahora ........ %d" % len(hechas))
    log("pendientes por descarga . %d carpeta(s) inestables o sin publicar · %d álbum(es) de Notion aún sin carpeta"
        % (cuenta.get("pendiente", 0), len(sin_carpeta)))
    log("sin fila en Notion ...... %d" % cuenta.get("sin_fila", 0))
    log("errores (3 intentos) .... %d%s" % (cuenta.get("error", 0), (" · nuevos: " + ", ".join(errores_pasada)) if errores_pasada else ""))
    log("filas con foto .......... %d de %d" % (con_foto, total_filas))
    log("portada v2 .............. %d puestas (%d reemplazan una vieja) · %d ya_correcta"
        % (len(hechas), len(reemplazadas), len(ya_correctas)))
    log("por revisar (paso 2) .... %d%s" % (cuenta.get("por_revisar", 0),
        (" → hojas: python %s --por-revisar" % os.path.join(os.path.dirname(os.path.abspath(__file__)), "revisar_portadas.py"))
        if cuenta.get("por_revisar") else ""))
    todas_dudosas = sorted(k for k, v in est["albumes"].items() if v.get("estado") == "portada_dudosa")
    log("portada_dudosa .......... %d%s" % (len(todas_dudosas), (": " + ", ".join(todas_dudosas)) if todas_dudosas else ""))
    todas_espalda = sorted(k for k, v in est["albumes"].items() if v.get("tipo") == "solo_espalda")
    log("solo_espalda ............ %d%s" % (len(todas_espalda), (": " + ", ".join(todas_espalda)) if todas_espalda else ""))
    if notion:
        log("peticiones a Notion ..... %d" % notion.peticiones)
    log("log: " + log.ruta)


if __name__ == "__main__":
    main()
