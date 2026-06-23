# Build — DJ Tracks Installer

Genera un instalador `.exe` que cualquier persona pueda hacer doble-click
para instalar la app en Windows, sin necesidad de tener Python.

## Resultado final

```
dist\installer\DJTracks-Setup-2.1.0.exe   ← esto es lo que repartes
```

El usuario hace doble-click → instalador → DJ Tracks aparece en el menú
inicio y en el escritorio. Sin Python, sin pip, sin nada.

## Requisitos para construir

| Herramienta | Para qué | Instalación |
|-------------|----------|-------------|
| **Python 3.10+** | Empaquetar la app | Ya lo tienes |
| **PyInstaller** | Generar el `.exe` | Se instala solo (`build.bat` lo hace) |
| **Inno Setup 6** | Generar el instalador | https://jrsoftware.org/isdl.php (gratis, 3 MB) |

> Si **no instalas** Inno Setup, `build.bat` igualmente generará una
> carpeta portable `dist\DJ Tracks\` que puedes comprimir en ZIP y
> distribuir. Funciona igual, pero el usuario tiene que descomprimir.

## Cómo construir

1. Asegúrate de que `ffmpeg.exe` está en la raíz del proyecto (ya lo está).
2. Doble-click en `build\build.bat`.
3. Espera 1–3 minutos. Al final tendrás:
   - **Carpeta portable**: `dist\DJ Tracks\` (zip y manda)
   - **Instalador**: `dist\installer\DJTracks-Setup-2.1.0.exe` (manda este)

## Notas importantes

### Dónde vive la configuración del usuario

Cuando alguien instala el `.exe`, sus datos (credenciales API, historial,
cola pendiente, logs) se guardan en:

```
%APPDATA%\DjTracks\config\
%APPDATA%\DjTracks\logs\
```

Cada usuario tiene su propia configuración. Al desinstalar, esta carpeta
se mantiene (los datos personales no se borran salvo que el usuario lo
quiera).

### Tamaño del instalador

Esperado: **~80–120 MB**. La mayoría es Python embebido + yt-dlp +
ffmpeg + dependencias. PyInstaller comprime con LZMA pero sigue siendo
grande porque empaqueta todo lo necesario.

### Antivirus / SmartScreen

Como el instalador no está firmado digitalmente, Windows mostrará un
aviso "Windows protegió tu PC" la primera vez. El usuario debe pulsar
"Más información" → "Ejecutar de todas formas". Para evitarlo, hay que
firmar el `.exe` con un certificado de Authenticode (~70€/año).

Antivirus de terceros pueden marcar falsos positivos en apps PyInstaller
sin firmar. Es una limitación conocida del bootloader de PyInstaller.

### Credenciales en el bundle

**NUNCA** dejes credenciales de Spotify en `config/settings.json` antes
de construir. PyInstaller **no** incluye `config/` en el bundle (sólo
los archivos listados en `dj_tracks.spec`), pero por seguridad: cada
usuario tiene que poner sus propias credenciales después de instalar.

### Probar el bundle antes de distribuirlo

Antes de mandar el instalador a alguien:
```cmd
cd dist\DJ Tracks
"DJ Tracks.exe"
```
La app debe abrirse igual que con `iniciar.bat`. Si crashea, mira
`%APPDATA%\DjTracks\logs\app.log`.

## Estructura de archivos

```
build/
├── build.bat          ← Doble-click aquí para construir todo
├── dj_tracks.spec     ← Configuración de PyInstaller
├── installer.iss      ← Configuración de Inno Setup
└── README.md          ← Este archivo
```
