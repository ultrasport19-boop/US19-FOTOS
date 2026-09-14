# Portadas de Yupoo → GitHub Pages → Notion

Pone en cada fila de **👕 Tienda — Ropa deportiva** (cruce por `Álbum ID` = nombre de
la carpeta) una portada con **la camiseta completa, de frente**, compuesta en un lienzo
cuadrado blanco para que Notion y la tienda la muestren entera.

## El comando (el mismo siempre)

```
powershell -ExecutionPolicy Bypass -File C:\yupoo_trabajo\codigo\subir_fotos.ps1
```

Se puede lanzar cinco veces al día: cada pasada toma solo lo que ya está listo y salta
lo hecho. Opciones: `--max 10`, `--solo ID,ID`, `--seco` (no publica ni escribe).

## Qué hace con cada carpeta

1. **Solo carpetas estables** del origen en OneDrive (que no toca: solo lee): imagen que
   se abre de verdad, nada modificado en 2 minutos, mismo tamaño en dos lecturas. Si no,
   queda `pendiente` para la próxima pasada. Copia a `C:\yupoo_fotos\<AlbumID>\`.
2. **Paso 1 – heurística** (`portadas.py`): una entrada por foto distinta del álbum
   (cada foto viene en miniatura y original; se detectan por dHash), fuera las de
   < 600 px. Con fondo claro y liso, el recuadro de la prenda descarta zooms (toca los
   4 bordes) y detalles (< 25 %). **Con fondo de textura (la reja del proveedor) el
   recuadro miente, así que ahí no descarta**: lo decide la vista.
3. **Paso 2 – visión**: `python revisar_portadas.py --por-revisar` genera
   `C:\yupoo_trabajo\revision\<ID>.jpg` (A-C = candidatas, debajo el resto, cuadrícula
   al 10 %). Quien mira decide y lo anota en `C:\yupoo_fotos\_portadas.json`:
   `{"<ID>": {"archivo", "tipo": frontal|solo_espalda|dudosa, "caja", "motivo", "version": 2}}`.
   Sin decisión, el álbum queda `por_revisar` y no se publica.
4. **Composición**: el recuadro se ajusta solo al contorno cuando los colores del fondo
   lo permiten (margen 5 %); si no, se usa el recuadro leído (margen 2 %). Lienzo
   1000×1000 blanco, prenda a ~90 % del lado mayor, sin deformar ni recortar la prenda.
   WebP calidad 80 (baja si pasa de 300 KB).
5. **Publicación**: `gh-pages` → `fotos/<ID>-v2.webp` (nombre nuevo: la caché del CDN no
   sirve la vieja), un commit por tanda de 200, y espera a que la URL responda 200.
6. **Notion**: `Foto` por importación de URL externa (File Upload API) **reemplazando** la
   anterior (no acumula) y `Foto URL` con la URL pública, estable, la que usa la tienda.
   `dudosa` deja la foto actual; si la elegida es la que ya estaba, `ya_correcta`.

## Estado

`C:\yupoo_fotos\_estado.json`: `hecho` · `pendiente` · `por_revisar` · `portada_dudosa` ·
`sin_fila` · `error` (3 fallos), más `portada_version: 2`. Notion es la verdad final: una
fila cuya `Foto URL` ya es `-v2.webp` se da por revisada aunque el estado se pierda. Para
reintentar un `error`, se borra su entrada.

## Seguridad

- El token de Notion sale de la variable de usuario `NOTION_TOKEN`. No va en el código,
  en el log, en el estado ni en un commit.
- Solo se escriben las columnas `Foto` y `Foto URL`.
