# DJ Tracks

[![Version](https://img.shields.io/github/v/release/trovira97/dj-tracks?style=flat-square)](https://github.com/trovira97/dj-tracks/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows-blue?style=flat-square)](https://github.com/trovira97/dj-tracks/releases/latest)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square)](https://www.python.org/)

> **Descargador de música pensado para DJs.** Pega un enlace de Spotify, Apple Music, SoundCloud, Bandcamp o YouTube y obtén el archivo en MP3/FLAC con metadatos completos: BPM, key (Camelot), género, sello, portada y ReplayGain — todo gracias a Beatport como fuente principal de metadata DJ.

---

## ✨ Características

- **5 plataformas en una app** — Spotify · Apple Music · SoundCloud · Bandcamp · YouTube
- **Metadatos curados** — Beatport (BPM/key/Camelot/sello/género) como fuente primaria, con caché en disco; GetSongBPM y `librosa` como fallback
- **Reproductor estilo Apple Music** — portada del álbum, scrubber, prev/next, vista expandida, cola integrada con el historial
- **Búsqueda multi-plataforma simultánea** — un solo query, resultados de todas las fuentes en paralelo
- **Cross-platform retry** — si una descarga falla por DRM/restricción, busca la misma canción en otras plataformas automáticamente
- **Auto-update integrado** — chequeo automático al arrancar contra GitHub Releases, descarga e instalación con un click desde Ajustes
- **Calidad máxima** — mantiene el codec original cuando es posible (FLAC de Bandcamp, opus de YouTube Music, etc.)
- **Detección y des-duplicación** — fingerprinting acústico opcional para evitar bajar dos veces el mismo track
- **Renombrado DJ opcional** — `Artist - Title [128 - 8A].mp3` listo para Rekordbox / Serato

## 📥 Instalación

1. Descarga **`DJ Tracks.zip`** de la [última release](https://github.com/trovira97/dj-tracks/releases/latest)
2. Extrae el zip donde quieras (ej. `C:\Programs\DJ Tracks\`)
3. Doble-click en **`DJ Tracks.exe`**

> ⚠️ Windows SmartScreen avisará la primera vez (*"Editor desconocido"*). Pulsa **"Más información"** → **"Ejecutar de todas formas"**. La app no está firmada digitalmente todavía.

A partir de aquí, la app se actualizará sola — verás un toast cuando haya una versión nueva.

---

## 🔑 Configuración de APIs

La mayoría de plataformas funcionan **sin configuración**. Sólo **Spotify** requiere credenciales (gratis, 2 minutos). Aquí está todo desglosado:

| Plataforma | Necesita config | Cómo |
|---|---|---|
| **Spotify** | ✅ Sí (Client ID + Secret) | Ver sección abajo |
| **Apple Music** | ❌ No | Usa la API pública iTunes Search |
| **SoundCloud** | ❌ No (auto-detecta) | Si falla la auto-detección, opcionalmente Client ID propio |
| **Bandcamp** | ❌ No | API pública de búsqueda |
| **YouTube** | ❌ No | yt-dlp lo gestiona internamente |
| **Beatport** (metadatos) | ❌ No | Scraping del SPA público, sin auth |
| **GetSongBPM** | ⚙️ Opcional | Sólo si quieres una fuente extra de BPM/key |

### 🎧 Spotify — paso a paso

Esto es lo único que **necesitas hacer una vez** para usar la funcionalidad completa de Spotify.

1. Ve a [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) e inicia sesión con tu cuenta de Spotify (la normal, no necesita Premium).
2. Pulsa **"Create app"**.
3. Rellena el formulario:
   - **App name**: `DJ Tracks` (o lo que quieras, sólo es interno)
   - **App description**: `Personal music downloader`
   - **Redirect URI**: `http://localhost:8888/callback` (cualquier URL local vale, no se usa)
   - **API/SDK**: marca **"Web API"**
   - Acepta los términos → **Save**
4. En la página de tu app, pulsa **"Settings"** (arriba a la derecha).
5. Copia el **Client ID**. Pulsa **"View client secret"** y copia el **Client Secret**.
6. En DJ Tracks: **Ajustes → Credenciales de API**, pega ambos valores y pulsa **Guardar**.

> 💡 Hay un botón **"❓ ¿Cómo configurar Spotify?"** en el panel de Ajustes que te abre un asistente con las mismas instrucciones.

### 🔊 SoundCloud — opcional

DJ Tracks **auto-detecta** el `client_id` público de SoundCloud al arrancar. Sólo necesitas configurarlo manualmente si la detección falla (raro). En ese caso:

1. Abre SoundCloud en el navegador, abre DevTools (F12) → pestaña **Network**.
2. Haz cualquier acción (reproducir un track, buscar algo).
3. Busca cualquier petición a `api-v2.soundcloud.com`. En la URL verás `?client_id=XXXXXXXX`.
4. Copia ese `client_id` en **Ajustes → Credenciales de API → SoundCloud · Client ID**.

### 🎵 GetSongBPM — opcional

Beatport ya cubre la inmensa mayoría de tracks de electrónica. GetSongBPM sólo aporta valor para géneros que Beatport no indexa (pop, hip-hop, rock). Si te interesa:

1. Ve a [getsongbpm.com/api](https://getsongbpm.com/api) y solicita una API key gratis (te llega por email en 1-2 días).
2. Pégala en **Ajustes → Análisis DJ → GetSongBPM API Key**.

---

## 🎚️ Uso básico

### Descargar por URL
Pega el enlace en la barra superior y pulsa Enter. Funciona con:
- Tracks individuales de Spotify / Apple Music / SoundCloud / Bandcamp / YouTube
- Álbumes / EPs de cualquier plataforma
- Playlists de Spotify
- Playlists de YouTube

### Buscar por texto
Escribe `Artist - Title` (o cualquier query). DJ Tracks consulta las 5 plataformas en paralelo y te muestra los resultados agrupados. Marca los que quieras y dale a **Descargar seleccionados**.

### Vista del historial
Cada track descargado aparece en **Historial** con:
- ▶ botón de reproducción inline (abre el mini-player tipo Apple Music)
- 🔁 botón de redescarga
- Badge **`BEATPORT`** / `DB` / `LOCAL` según de dónde vinieron los metadatos
- Etiqueta de plataforma + calidad + fecha

### Modo DJ
En **Ajustes → Análisis DJ** puedes activar:
- **Renombrado DJ** — el archivo final lleva `[128 - 8A]` al nombre (BPM + Camelot)
- **ReplayGain** — escribe tags de loudness para volumen consistente entre tracks
- **Quality check** — avisa si el archivo descargado tiene bitrate real menor del que pediste
- **Acoustic dedup** — fingerprinting para detectar duplicados aunque tengan distinto título

---

## 🔄 Auto-update

DJ Tracks consulta GitHub Releases automáticamente al arrancar (toggleable en **Ajustes → Buscar actualizaciones al iniciar**). Cuando hay versión nueva:

1. Verás un toast: **"🆕 Nueva versión disponible: vX.Y.Z"**
2. **Ajustes → Buscar actualizaciones de DJ Tracks** → confirmas → descarga e instala
3. La app se cierra, reemplaza los archivos, y se vuelve a abrir sola

Si prefieres actualizar manual, descarga el `.zip` de la release y extráelo encima de la instalación actual.

---

## 🛠️ Para desarrolladores

### Ejecutar desde código fuente

```bash
git clone https://github.com/trovira97/dj-tracks
cd dj-tracks
python -m pip install -r requirements.txt
python main.py
```

Requiere Python 3.10+ y `ffmpeg.exe` en el PATH (o en la carpeta raíz del proyecto).

### Estructura

```
dj-tracks/
├── main.py                   # Entry point
├── core/
│   ├── controller.py         # AppController — orquesta queue, descargas, post-proceso
│   └── search_manager.py     # Fan-out multi-plataforma
├── ui/
│   └── gui.py                # CustomTkinter — toda la UI
├── downloader/
│   └── audio_downloader.py   # yt-dlp wrapper, clasificación de errores, retry cross-platform
├── providers/                # Spotify / Apple / SoundCloud / Bandcamp / YouTube
├── metadata/
│   ├── beatport.py           # Cliente Beatport (scrape + cache)
│   ├── dj_metadata.py        # Pipeline de enriquecimiento DJ
│   └── metadata_writer.py    # mutagen (ID3, Vorbis, MP4)
└── utils/
    ├── app_updater.py        # Auto-update vía GitHub Releases
    ├── audio_player.py       # pygame mixer + cola
    └── history_manager.py    # Persistencia del historial
```

### Tests

```bash
python -m pytest tests/ -q
```

### Compilar el `.exe`

```bash
build\build.bat
```

Genera `dist/DJ Tracks/` con el bundle PyInstaller. Para distribuir, zipea esa carpeta entera.

---

## ⚖️ Aviso legal

DJ Tracks es una herramienta para **uso personal** que automatiza descargas mediante APIs públicas y `yt-dlp`. Tú eres responsable de cumplir los términos de servicio de cada plataforma y la legislación de copyright de tu país. Los autores no nos responsabilizamos del uso que hagas de la herramienta.

**No descargues música de la que no tengas derecho a obtener una copia.**

Beatport se usa **únicamente como fuente de metadatos** — no se descarga audio de Beatport en ningún caso (su catálogo es de pago y está protegido con DRM real).

---

## 📜 Licencia

Sin licencia explícita por ahora — esto significa que el código es **"todos los derechos reservados"** por defecto. Si quieres reutilizar partes, abre un issue.

---

## 💬 Soporte

- **Server Discord**: [discord.gg/cNkh8Yd2A7](https://discord.gg/cNkh8Yd2A7) — ayuda, canal de donantes, anuncios
- **Issues / bugs / sugerencias**: [github.com/trovira97/dj-tracks/issues](https://github.com/trovira97/dj-tracks/issues)
- **Donar**: [ko-fi.com/trovira_97](https://ko-fi.com/trovira_97) — desbloquea descargas ilimitadas para siempre
