# Portadas de Yupoo → GitHub Pages → Notion

Pone la portada de cada álbum de Yupoo en la fila de **👕 Tienda — Ropa deportiva**
cuyo `Álbum ID` coincide con el nombre de la carpeta.

## El comando (el mismo siempre)

```
powershell -ExecutionPolicy Bypass -File C:\yupoo_trabajo\codigo\subir_fotos.ps1
```

Se puede lanzar cinco veces al día: cada pasada toma solo lo que ya está listo y
salta lo hecho. Opciones: `--max 10` (piloto), `--solo ID,ID`, `--seco` (no publica
ni escribe).

## Qué hace con cada carpeta

1. **Solo carpetas estables** del origen en OneDrive (que no toca: solo lee): imagen
   que se abre de verdad, nada modificado en 2 minutos, mismo tamaño en dos lecturas.
   Si no, queda `pendiente` para la próxima pasada.
2. Copia a `C:\yupoo_fotos\<AlbumID>\`.
3. **Portada = la foto 1 del álbum en su versión más grande.** Cada foto viene dos
   veces (miniatura y original); se busca la gemela por huella visual (dHash).
4. WebP, lado mayor 1000 px, calidad 80 (baja hasta 50 si pasa de 300 KB).
5. Publica en `gh-pages` → `https://ultrasport19-boop.github.io/US19-FOTOS/fotos/<AlbumID>.webp`,
   un commit por tanda de 200, y espera a que la URL responda 200.
6. En Notion: `Foto` por importación de URL externa (File Upload API) y `Foto URL`
   con la URL pública, que es estable y la que usa la tienda.

## Estado

`C:\yupoo_fotos\_estado.json`: `hecho` · `pendiente` · `sin_fila` · `error` (3 fallos),
con intentos y mensaje. Pero la verdad final es Notion: una fila que ya tiene `Foto` se
salta aunque el estado se pierda. Para reintentar un `error`, se borra su entrada.

## Seguridad

- El token de Notion sale de la variable de usuario `NOTION_TOKEN`. No va en el código,
  en el log, en el estado ni en un commit.
- Solo se escriben las columnas `Foto` y `Foto URL`.
