"""
portadas.py - Elegir la portada de un álbum: la camiseta completa, de frente.

Paso 1 (aquí): heurística que descarta lo obvio y ordena las candidatas.
Paso 2 (fuera): alguien con visión mira las 3 mejores y decide; la decisión
se guarda en C:\\yupoo_fotos\\_portadas.json y el proceso de subida la aplica.

Además compone la portada en un lienzo cuadrado blanco de 1000 px, con la
prenda centrada ocupando ~90 %, sin deformar ni recortar: Notion recorta las
tarjetas de galería y una foto vertical se vería cortada.
"""
import io
import os
import re

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

EXT_IMG = (".jpg", ".jpeg", ".png", ".webp", ".gif")
LADO_MIN = 600            # descarta imágenes con lado mayor menor
UMBRAL_GEMELA = 4         # bits de dHash para «es la misma foto en otra resolución»
TRABAJO_PX = 256          # tamaño de trabajo para medir la prenda
UMBRAL_FONDO = 38         # diferencia con el color del borde para decir «prenda»
APERTURA = 7              # borra estructuras finas (reja, costuras de la pared)
MARGEN_BORDE = 0.02       # «toca el borde» si el recuadro queda a menos del 2 %


def numero(nombre):
    m = re.match(r"(\d+)", nombre)
    return (int(m.group(1)) if m else 10 ** 9, nombre.lower())


def dhash(im):
    g = im.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(g.get_flattened_data()) if hasattr(g, "get_flattened_data") else list(g.getdata())
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (px[y * 9 + x] > px[y * 9 + x + 1])
    return bits


def unicas(carpeta):
    """Una entrada por foto distinta del álbum, en su versión más grande."""
    fotos = []
    for f in sorted((f for f in os.listdir(carpeta) if f.lower().endswith(EXT_IMG)), key=numero):
        ruta = os.path.join(carpeta, f)
        try:
            with Image.open(ruta) as im:
                im.load()
                fotos.append({"archivo": f, "ruta": ruta, "ancho": im.size[0], "alto": im.size[1],
                              "lado": max(im.size), "hash": dhash(im)})
        except Exception:
            continue
    grupos = []
    for f in fotos:
        for g in grupos:
            if bin(g[0]["hash"] ^ f["hash"]).count("1") <= UMBRAL_GEMELA:
                g.append(f)
                break
        else:
            grupos.append([f])
    out = []
    for g in grupos:
        mejor = max(g, key=lambda x: x["lado"])
        mejor["orden"] = min(numero(x["archivo"])[0] for x in g)
        mejor["versiones"] = [x["archivo"] for x in g]
        out.append(mejor)
    return out


def mascara(im):
    """Máscara de la prenda a TRABAJO_PX: lo que se aparta del color del borde,
    con apertura para borrar la reja y las líneas finas del fondo."""
    peq = ImageOps.exif_transpose(im).convert("RGB")
    peq.thumbnail((TRABAJO_PX, TRABAJO_PX), Image.LANCZOS)
    w, h = peq.size
    borde = []
    px = peq.load()
    for x in range(w):
        borde += [px[x, 0], px[x, 1], px[x, h - 1], px[x, h - 2]]
    for y in range(h):
        borde += [px[0, y], px[1, y], px[w - 1, y], px[w - 2, y]]
    fondo = tuple(sorted(c[i] for c in borde)[len(borde) // 2] for i in range(3))
    dif = ImageChops.difference(peq, Image.new("RGB", peq.size, fondo))
    r, g, b = dif.split()
    d = ImageChops.lighter(ImageChops.lighter(r, g), b)
    m = d.point(lambda v: 255 if v > UMBRAL_FONDO else 0)
    m = m.filter(ImageFilter.MinFilter(APERTURA)).filter(ImageFilter.MaxFilter(APERTURA))
    return m, fondo


def borde_uniforme(im):
    """¿El borde de la foto es un fondo claro y liso? Medido el 13-sep: el
    proveedor fotografía muchas camisetas sobre una REJA metálica (blanco y
    negro), y los zooms tienen de «borde» la propia tela. En los dos casos el
    recuadro miente; solo se confía en él con un borde claro y uniforme."""
    peq = ImageOps.exif_transpose(im).convert("L")
    peq.thumbnail((TRABAJO_PX, TRABAJO_PX), Image.LANCZOS)
    w, h = peq.size
    px = peq.load()
    b = [px[x, y] for x in range(w) for y in (0, 1, h - 2, h - 1)] + \
        [px[x, y] for y in range(h) for x in (0, 1, w - 2, w - 1)]
    media = sum(b) / float(len(b))
    desv = (sum((v - media) ** 2 for v in b) / float(len(b))) ** 0.5
    return media >= 170 and desv <= 22, round(media), round(desv)


def medir(ruta):
    """Recuadro de la prenda y señales para descartar zooms y detalles."""
    with Image.open(ruta) as im:
        im.load()
        m, fondo = mascara(im)
        uniforme, media, desv = borde_uniforme(im)
    w, h = m.size
    caja = m.getbbox()
    base = {"fondo": fondo, "uniforme": uniforme, "borde_media": media, "borde_desv": desv}
    if not caja:
        return dict(base, area=0.0, bordes=0, caja=None, relleno=0.0)
    x0, y0, x1, y1 = caja
    mx, my = MARGEN_BORDE * w, MARGEN_BORDE * h
    bordes = sum([x0 <= mx, y0 <= my, x1 >= w - mx, y1 >= h - my])
    area = (x1 - x0) * (y1 - y0) / float(w * h)
    hist = m.crop(caja).histogram()
    relleno = hist[255] / float(max(1, (x1 - x0) * (y1 - y0)))   # cuánto del recuadro es prenda
    return dict(base, area=round(area, 3), bordes=bordes, relleno=round(relleno, 3),
                caja=[x0 / w, y0 / h, x1 / w, y1 / h])


def clasificar(med, lado):
    """(válida, motivo, puntaje) según las reglas de Diego."""
    if lado < LADO_MIN:
        return False, "lado mayor %d px < %d" % (lado, LADO_MIN), 0.0
    if not med["uniforme"]:
        # Sin fondo claro y liso el recuadro no dice nada: no se descarta, lo decide la vista.
        med["caja"] = None
        return True, "fondo con textura (borde %d±%d): lo decide la vista" % (med["borde_media"], med["borde_desv"]), 0.4
    if med["caja"] is None:
        return False, "no se distingue la prenda del fondo", 0.0
    if med["bordes"] >= 4:
        return False, "toca los cuatro bordes: zoom", 0.0
    if med["area"] < 0.25:
        return False, "ocupa %.0f %% (< 25 %%): detalle suelto" % (100 * med["area"]), 0.0
    # candidata: se prefiere área cercana a 60 %, margen en los cuatro lados y buen relleno
    puntaje = 1.0 - abs(med["area"] - 0.60) * 1.5
    puntaje -= 0.25 * med["bordes"]
    puntaje += 0.3 * min(med["relleno"], 0.8)
    en_rango = 0.35 <= med["area"] <= 0.85 and med["bordes"] == 0
    motivo = ("plano completo: %.0f %% con margen en los 4 lados" if en_rango
              else "posible: %.0f %%, toca %d borde(s)") % ((100 * med["area"],) if en_rango else (100 * med["area"], med["bordes"]))
    return True, motivo, round(puntaje + (0.5 if en_rango else 0.0), 3)


def candidatas(carpeta, n=3):
    """Todas las fotos distintas, medidas y ordenadas; las n primeras son las candidatas."""
    todas = []
    for f in unicas(carpeta):
        med = medir(f["ruta"])
        ok, motivo, puntaje = clasificar(med, f["lado"])
        todas.append(dict(f, **med, valida=ok, motivo=motivo, puntaje=puntaje))
    todas.sort(key=lambda x: (-x["valida"], -x["puntaje"], x["orden"]))
    return todas[:n], todas


def hoja(titulo, fotos, destino, lado=256, marcar=None, cols=None):
    """Hoja de contacto: miniaturas etiquetadas A, B, C... con su medida y una
    cuadrícula tenue cada 10 % para poder leer el recuadro de la prenda."""
    cols = cols or (min(len(fotos), 5) or 1)
    filas = (len(fotos) + cols - 1) // cols
    alto_txt = 34
    lienzo = Image.new("RGB", (cols * (lado + 8) + 8, 30 + filas * (lado + alto_txt + 8)), "white")
    d = ImageDraw.Draw(lienzo)
    d.text((8, 8), titulo, fill=(0, 0, 0))
    for i, f in enumerate(fotos):
        x = 8 + (i % cols) * (lado + 8)
        y = 30 + (i // cols) * (lado + alto_txt + 8)
        with Image.open(f["ruta"]) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((lado, lado), Image.LANCZOS)
            ox, oy = x + (lado - im.size[0]) // 2, y + (lado - im.size[1]) // 2
            lienzo.paste(im, (ox, oy))
        for k in range(1, 10):   # cuadrícula cada 10 % (más marcada en 50 %)
            col = (255, 0, 255) if k == 5 else (255, 140, 255)
            gx, gy = ox + im.size[0] * k / 10.0, oy + im.size[1] * k / 10.0
            for t in range(0, im.size[1], 6):
                d.point((gx, oy + t), fill=col)
            for t in range(0, im.size[0], 6):
                d.point((ox + t, gy), fill=col)
        if f.get("caja"):
            cx0, cy0, cx1, cy1 = f["caja"]
            d.rectangle([ox + cx0 * im.size[0], oy + cy0 * im.size[1], ox + cx1 * im.size[0], oy + cy1 * im.size[1]],
                        outline=(0, 160, 0) if f.get("valida") else (200, 0, 0), width=2)
        etiqueta = "%s  %s  %dpx" % (chr(65 + i), f["archivo"], f["lado"])
        if marcar and f["archivo"] == marcar:
            etiqueta += "  <actual>"
        d.text((x, y + lado + 2), etiqueta, fill=(0, 0, 0))
        d.text((x, y + lado + 16), "%s%.0f%% b%d" % ("ok " if f.get("valida") else "x ", 100 * f.get("area", 0), f.get("bordes", 0)),
               fill=(0, 120, 0) if f.get("valida") else (180, 0, 0))
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    lienzo.save(destino, quality=85)
    return destino


def refinar_caja(ruta, caja, holgura=0.03, umbral=55, px_trabajo=320):
    """Ajusta el recuadro que se leyó a ojo al contorno real de la prenda.

    Los colores del fondo se toman FUERA del recuadro (reja, pared, pasto,
    maniquí) y dentro se marca lo que no se parece a ninguno. Si la señal no es
    fiable (prenda del mismo color que el fondo, máscara rala o diminuta) se
    devuelve el recuadro original: nunca recorta más allá de lo que se leyó."""
    if not caja:
        return None, "sin recuadro"
    with Image.open(ruta) as im:
        im.load()
        im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((px_trabajo, px_trabajo), Image.LANCZOS)
    W, H = im.size
    x0, y0, x1, y1 = caja
    X0, Y0, X1, Y1 = int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)
    tiras = [im.crop(c) for c in ((0, 0, W, Y0), (0, Y1, W, H), (0, Y0, X0, Y1), (X1, Y0, W, Y1))
             if c[2] - c[0] >= 4 and c[3] - c[1] >= 4]
    if sum(t.size[0] * t.size[1] for t in tiras) < 0.04 * W * H:   # casi no hay fondo fuera: franja del borde
        g = int(0.06 * min(W, H))
        tiras = [im.crop((0, 0, W, g)), im.crop((0, H - g, W, H)), im.crop((0, 0, g, H)), im.crop((W - g, 0, W, H))]
    ancho = sum(t.size[0] * t.size[1] for t in tiras)
    anillo = Image.new("RGB", (ancho, 1))
    pos = 0
    for t in tiras:
        datos = list(t.get_flattened_data()) if hasattr(t, "get_flattened_data") else list(t.getdata())
        fila = Image.new("RGB", (len(datos), 1))
        fila.putdata(datos)
        anillo.paste(fila, (pos, 0))
        pos += len(datos)
    pal = anillo.quantize(16, method=Image.Quantize.MEDIANCUT).convert("RGB")
    colores = [c for _, c in (pal.getcolors(1 << 16) or [])]
    hx0, hy0 = max(0, int((x0 - holgura) * W)), max(0, int((y0 - holgura) * H))
    hx1, hy1 = min(W, int((x1 + holgura) * W)), min(H, int((y1 + holgura) * H))
    dentro = im.crop((hx0, hy0, hx1, hy1))
    dmin = None
    for c in colores:
        r, g, b = ImageChops.difference(dentro, Image.new("RGB", dentro.size, c)).split()
        d = ImageChops.lighter(ImageChops.lighter(r, g), b)
        dmin = d if dmin is None else ImageChops.darker(dmin, d)
    m = dmin.point(lambda v: 255 if v > umbral else 0)
    m = m.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(5))
    bb = m.getbbox()
    if not bb:
        return caja, "sin señal: se usa el recuadro leído"
    bx0, by0, bx1, by1 = bb
    area_bb = (bx1 - bx0) * (by1 - by0)
    relleno = m.crop(bb).histogram()[255] / float(max(1, area_bb))
    area_caja = (X1 - X0) * (Y1 - Y0)
    if area_bb < 0.35 * area_caja or relleno < 0.30:
        return caja, "señal débil (área %.0f %%, relleno %.0f %%): se usa el recuadro leído" % (
            100.0 * area_bb / max(1, area_caja), 100 * relleno)
    nueva = [(hx0 + bx0) / float(W), (hy0 + by0) / float(H), (hx0 + bx1) / float(W), (hy0 + by1) / float(H)]
    return [round(v, 4) for v in nueva], "ajustada al contorno (relleno %.0f %%)" % (100 * relleno)


MARGEN_AJUSTADA = 0.05   # el contorno automático se queda corto en puntas de manga del color del fondo
MARGEN_LEIDA = 0.02      # el recuadro leído a ojo ya trae holgura


def caja_final(ruta, caja):
    """(caja, margen, nota): el recuadro que se usa para componer y su margen."""
    nueva, nota = refinar_caja(ruta, caja)
    ajustada = nueva is not None and nueva != caja
    return nueva, (MARGEN_AJUSTADA if ajustada else MARGEN_LEIDA), nota


def componer(ruta, caja=None, lado=1000, ocupacion=0.90, calidades=(80, 74, 68, 62, 56, 50),
             objetivo=300 * 1024, margen=0.02):
    """Lienzo cuadrado blanco de `lado` px con la prenda centrada ocupando ~90 %.
    Recorta al recuadro de la prenda + margen (nunca dentro de la prenda),
    escala sin deformar y centra. Devuelve (bytes_webp, (ancho, alto) de la prenda, calidad)."""
    with Image.open(ruta) as im:
        im.load()
        im = ImageOps.exif_transpose(im)
        tiene_alfa = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        im = im.convert("RGBA" if tiene_alfa else "RGB")
        W, H = im.size
        if caja:
            x0, y0, x1, y1 = caja
            x0 = max(0.0, x0 - margen); y0 = max(0.0, y0 - margen)
            x1 = min(1.0, x1 + margen); y1 = min(1.0, y1 + margen)
            im = im.crop((int(x0 * W), int(y0 * H), int(round(x1 * W)), int(round(y1 * H))))
        destino_max = int(lado * ocupacion)
        esc = min(destino_max / float(im.size[0]), destino_max / float(im.size[1]))
        nuevo = (max(1, int(round(im.size[0] * esc))), max(1, int(round(im.size[1] * esc))))
        im = im.resize(nuevo, Image.LANCZOS)
        lienzo = Image.new("RGB", (lado, lado), "white")
        pos = ((lado - nuevo[0]) // 2, (lado - nuevo[1]) // 2)
        if im.mode == "RGBA":
            lienzo.paste(im, pos, im)
        else:
            lienzo.paste(im, pos)
    for q in calidades:
        buf = io.BytesIO()
        lienzo.save(buf, "WEBP", quality=q, method=6)
        if buf.tell() <= objetivo:
            break
    return buf.getvalue(), nuevo, q
