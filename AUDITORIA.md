# 🔍 Auditoría DJ Tracks — pre-build

Fecha: 2026-06-13
Versión auditada: `2.1.0` (HEAD = `ef683c7`)

---

## 1. Calidad del código

| Área | Resultado |
|------|-----------|
| Sintaxis Python (44 archivos) | ✅ Todos parsean limpio |
| Test suite (`pytest tests/`) | ✅ **115/115 OK** |
| Imports de módulos clave (22) | ✅ Todos resuelven |
| `print()` debug perdidos | ✅ Ninguno |
| `breakpoint() / pdb` olvidados | ✅ Ninguno |
| Secretos hardcoded | ✅ Ninguno en tu código (sólo en `.vendor/` de terceros, no se empaqueta) |
| `TODO/FIXME/XXX` pendientes | ✅ Ninguno real (los "TXXX" son nombres de tags ID3) |

## 2. Dependencias

| Paquete | Versión | Estado |
|---------|---------|--------|
| customtkinter | 5.2.2 | ✅ |
| Pillow | 12.2.0 | ✅ |
| yt-dlp | **2026.06.09** | ✅ última versión |
| spotdl | 4.5.0 | ✅ |
| spotipy | instalado | ✅ |
| mutagen | instalado | ✅ |
| requests | 2.34.2 | ✅ |
| platformdirs | 4.10.0 | ✅ |
| tkinterdnd2 | instalado | ✅ opcional |
| qrcode | instalado | ✅ opcional |
| tls_client | instalado | ✅ dep de spotdl |

## 3. Seguridad

| Comprobación | Resultado |
|--------------|-----------|
| `.gitignore` protege `settings.json` | ✅ |
| `.gitignore` protege `history.json`, `queue.json` | ✅ |
| `.gitignore` protege `.cache` (token Spotify) | ✅ |
| `config/` excluido del bundle | ✅ (PyInstaller spec sólo incluye `assets/` + `ffmpeg.exe`) |
| Credenciales del usuario → `%APPDATA%/DjTracks/` | ✅ |

## 4. Funciones principales auditadas

| Función | Estado |
|---------|--------|
| Búsqueda por texto (4 plataformas en paralelo) | ✅ |
| Búsqueda de álbumes + multi-selección | ✅ |
| Motor dual: spotdl → yt-dlp fallback | ✅ |
| Bug 403 YouTube (sin Deno) | ✅ Resuelto con `player_client` rotativo |
| Análisis DJ (BPM / Camelot / ReplayGain) | ✅ |
| Detección de duplicados acústicos | ⚠️ Requiere ffmpeg con Chromaprint (el incluido no lo trae) |
| Asistente de configuración Spotify | ✅ |
| Botón redescarga en historial | ✅ |
| Actualización yt-dlp + reinicio automático | ✅ |
| Persistencia de cola | ✅ |
| Notificaciones nativas Win/Mac/Linux | ✅ |
| Drag & drop URLs | ✅ |
| Atajos de teclado (Ctrl+F/D/H/Q) | ✅ |
| Single instance lock | ✅ |
| Window geometry persist | ✅ |
| Donaciones cripto | ✅ |
| Atomic writes (config/history/queue) | ✅ |
| Subprocess silencioso (Windows) | ✅ |
| Bandcamp / SoundCloud descarga directa | ✅ |

## 5. Bundle / Distribución

| Comprobación | Resultado |
|--------------|-----------|
| `main.py` | ✅ presente |
| `assets/icon.ico` | ✅ 104 KB |
| `ffmpeg.exe` (raíz) | ✅ 97 MB |
| `.vendor/yt_dlp/__pyinstaller/hook-yt_dlp.py` | ✅ presente |
| `build/dj_tracks.spec` | ✅ con `collect_all("spotdl")` |
| `build/build.bat` detecta system Python 3.12 | ✅ |
| PyInstaller 6.20.0 | ✅ instalado |
| Comparison de versión yt-dlp con normalización | ✅ |

## 6. Limitaciones conocidas (no son bugs)

- **Spotify Developer App necesita Premium** — Spotify cambió la política en 2024.
  La app degrada limpiamente: spotdl se desactiva para la sesión, yt-dlp asume.
- **BPM/Camelot** — requiere API key gratuita de getsongbpm.com **o** instalar `librosa`.
- **Chromaprint** — el ffmpeg incluido no lo trae. Si el usuario instala un build
  completo de ffmpeg (gyan.dev o BtbN) la detección de duplicados se activa sola.

## 7. Veredicto

✅ **Listo para empaquetar**.  Sin bugs bloqueantes, sin código sospechoso,
dependencias al día. La build PyInstaller se está generando en `final test/`.
