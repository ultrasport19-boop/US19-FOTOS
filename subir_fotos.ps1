# Lanzador de subir_fotos.py: el mismo comando sirve siempre.
#   powershell -ExecutionPolicy Bypass -File C:\yupoo_trabajo\codigo\subir_fotos.ps1
#   ...\subir_fotos.ps1 --max 10        (piloto)
#   ...\subir_fotos.ps1 --seco          (prueba sin publicar ni escribir en Notion)
# El token de Notion se lee de la variable de usuario NOTION_TOKEN (Windows la
# guarda en el registro; una ventana abierta antes de crearla no la ve, por eso
# se lee también de ahí). Nunca se imprime.
$tok = $env:NOTION_TOKEN
if (-not $tok) { $tok = [Environment]::GetEnvironmentVariable('NOTION_TOKEN', 'User') }
if (-not $tok) {
  Write-Host 'Falta la variable de usuario NOTION_TOKEN (el token de la integración de Notion).' -ForegroundColor Red
  Write-Host 'Créala en: Inicio > «Editar las variables de entorno de esta cuenta» > Nueva.' -ForegroundColor Yellow
  exit 1
}
$env:NOTION_TOKEN = $tok
$env:PYTHONUTF8 = '1'
python (Join-Path $PSScriptRoot 'subir_fotos.py') @args
exit $LASTEXITCODE
