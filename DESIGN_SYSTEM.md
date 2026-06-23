# DJ Tracks — Design System v2.0
## Sistema de Diseño Visual Profesional

---

## 1. SISTEMA DE TEMAS

### Dark Pro (default)
| Token        | Valor     | Uso                        |
|--------------|-----------|----------------------------|
| bg           | #08080F   | Fondo raíz                 |
| sidebar      | #0B0B17   | Rail de navegación         |
| panel        | #0F0F1D   | Paneles de contenido       |
| card         | #141426   | Cards / filas              |
| card_hover   | #1A1A32   | Hover sobre cards          |
| surface      | #17172C   | Inputs, sub-superficies    |
| border       | #1E1E3A   | Bordes sutiles             |
| border_focus | #2C2C52   | Bordes en foco             |
| accent       | #00C8FF   | Acento primario (cian)     |
| accent_dim   | #0088AA   | Acento oscurecido          |
| accent2      | #7C3AED   | Secundario (púrpura)       |
| text         | #DCE0F5   | Texto primario             |
| text_mid     | #8088AA   | Texto secundario           |
| text_dim     | #404060   | Texto desactivado          |
| success      | #00D48A   | Estado OK                  |
| error        | #FF4466   | Estado error               |
| warning      | #FFB020   | Estado advertencia         |

### Neon Blue
accent: #1E90FF  bg: #020208  sidebar: #040410

### Neon Purple  
accent: #A020FF  bg: #06020C  sidebar: #0A0414

### Carbon Black
accent: #FF6B00  bg: #080808  sidebar: #0C0C0C

---

## 2. TIPOGRAFÍA

| Rol              | Fuente      | Tamaño | Peso  |
|------------------|-------------|--------|-------|
| Brand            | Sistema     | 17px   | Bold  |
| Titulo panel     | Sistema     | 11px   | Bold  |
| Track title      | Sistema     | 13px   | Bold  |
| Artista          | Sistema     | 11px   | Normal|
| Metadata         | Sistema     | 10px   | Normal|
| Monospace (path) | Consolas    | 9px    | Normal|
| Badge            | Sistema     | 9px    | Bold  |
| Status bar       | Sistema     | 8px    | Normal|

---

## 3. LAYOUT GENERAL

```
┌──────────────────────────────────────────────────────────────────┐
│  SIDEBAR (196px)  │  TOPBAR (50px)                               │
│  ─────────────    ├──────────────────────────────────────────────┤
│  ♪ DJ TRACKS      │  [TITULO PANEL]              [Ctrl+F hint]   │
│  DOWNLOADER       ├──────────────────────────────────────────────┤
│                   │                                              │
│  ▌ DASHBOARD      │           ÁREA DE CONTENIDO                  │
│    BUSCAR         │                                              │
│    DESCARGAS      │    (Dashboard / Search / Downloads /         │
│    HISTORIAL      │     History / Settings)                      │
│    AJUSTES        │                                              │
│                   │                                              │
│  ─────────────    │                                              │
│  v2.0 · yt-dlp   │                                              │
├───────────────────┴──────────────────────────────────────────────┤
│  STATUS BAR (22px)  DJ Tracks · yt-dlp · ...    ● Todos listos  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. DASHBOARD

```
┌─────────────────────────────────────────────────────────────────┐
│  RESUMEN                                                        │
│                                                                 │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────┐│
│  │  HOY         │ │  TOTAL       │ │  EN COLA     │ │  OK %  ││
│  │  ──────      │ │  ──────      │ │  ──────      │ │  ─── ──││
│  │    12        │ │   347        │ │    3         │ │  98%   ││
│  │ descargas    │ │  descargas   │ │  pendientes  │ │  éxito ││
│  └──────────────┘ └──────────────┘ └──────────────┘ └────────┘│
│                                                                 │
│  PLATAFORMAS                     ÚLTIMAS DESCARGAS              │
│  ┌──────────────────────────┐    ┌───────────────────────────┐ │
│  │ SP ████████████ 58%      │    │ ✓ Artist - Track.mp3      │ │
│  │ AM ██████       28%      │    │ ✓ Artist - Track.flac     │ │
│  │ SC ████         14%      │    │ ✗ Artist - Track (error)  │ │
│  └──────────────────────────┘    │ ✓ Artist - Track.mp3      │ │
│                                  │ ✓ Artist - Track.mp3      │ │
│                                  └───────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. BUSCADOR

```
┌─────────────────────────────────────────────────────────────────┐
│  ┌─────────────────────────────────────────── [✕] [Buscar]─┐   │
│  │  🔍  Escribe artista, canción, o pega una URL...         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  [Todas] [Spotify] [Apple Music] [SoundCloud]    [Lista][Grid]   │
│                                                                  │
│  ── FILTROS ──────────────────────────────────────────────────   │
│  Duración: [─────────────────────] 1:00 – 10:00                │
│  Año:      [Cualquiera ▼]                                       │
│                                                                  │
│  12 resultados · SP 5  AM 4  SC 3  —  + para añadir            │
│  ─────────────────────────────────────────────────────────────  │
│  ▌ [cover] Track Title                          SPOTIFY    [+]  │
│             Artist Name · Album · 3:47 · 2023                   │
│  ─────────────────────────────────────────────────────────────  │
│  ▌ [cover] Track Title                          APPLE MUSIC[+]  │
│  ...                                                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. HISTORIAL

```
┌─────────────────────────────────────────────────────────────────┐
│  HISTORIAL  [347 tracks]  [Buscar...]  [Exportar CSV] [JSON]    │
│  ──────────────────────────────────────────────────────────     │
│  ESTADO    TITULO            ARTISTA     PLATAFORMA  CALIDAD    │
│  ✓ LISTO   Track Name        Artist      Spotify     MP3 320    │
│  ✗ ERROR   Track Name        Artist      SoundCloud  —          │
│  ✓ LISTO   Track Name        Artist      Apple       FLAC       │
│  ...                                                             │
│  ──────────────────────────────────────────────────────────     │
│  [← Anterior]                                    [Siguiente →]  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. AJUSTES

```
┌─────────────────────────────────────────────────────────────────┐
│  TEMA VISUAL                                                    │
│  [Dark Pro ●] [Neon Blue] [Neon Purple] [Carbon Black]         │
│                                                                  │
│  DESCARGA                                                       │
│  Carpeta: [/ruta/destino/...]                    [···]          │
│  Formato: [MP3 ▼]   Calidad: [320k ▼]                          │
│  Estructura: [{artist}/{album}/{artist} - {title}]              │
│                                                                  │
│  CREDENCIALES API                                               │
│  Spotify Client ID:     [________________________]              │
│  Spotify Client Secret: [••••••••••••••••••••••••]              │
│  SoundCloud Client ID:  [________________________]              │
│                                                                  │
│  [      Guardar configuración      ]                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. COMPONENTES

### StatCard
- Fondo: card color con borde acento izquierdo (3px)
- Número grande (22px bold, color acento)
- Label secundario (10px, text_dim)
- Padding: 16px

### TrackRow (lista)
- Altura: 76px
- Stripe izquierdo: 3px color plataforma
- Cover: 56x56px redondeado
- Título: 13px bold
- Artista: 11px text_mid
- Metadata: 10px text_dim (álbum · duración · año)
- Botón +: 36x36 circular accent
- Hover: fondo card_hover

### TrackCard (grid)
- 185x275px
- Stripe top: 3px color plataforma
- Cover: 155x155px
- Título: 12px bold
- Artista + año: 10px text_mid
- Duración: monospace 9px
- Botón +: 34x30

### QueueRow
- Stripe izquierdo: 3px plataforma
- Barra progreso: 3px altura, animada
- Badge estado: pill coloreado
- DONE: fondo verde oscuro + path del archivo
- ERROR: fondo rojo oscuro + mensaje

### MiniWaveform
- Canvas 60x20px
- Barras verticales aleatorias centradas
- Color: acento con opacidad 40%
- Hover: acento 80%

### StatusBadge
- Pill 98px ancho
- Corner radius 4px
- Colores por estado

### Toast
- Corner radius 8px
- Stripe izquierdo 3px
- Auto-dismiss 2.8s
- Posición: bottom-right

---

## 9. MICROINTERACCIONES

| Acción          | Efecto                                           |
|-----------------|--------------------------------------------------|
| Hover TrackRow  | bg card → card_hover (instant)                   |
| Click + añadir  | Botón → ✓ verde, row flash                      |
| Search loading  | Botón pulsa ·  ··  ···  (220ms)                  |
| Guardar config  | Botón → verde "✓ Guardado" → vuelve (1.8s)      |
| DONE download   | Row tint verde oscuro, path aparece              |
| ERROR download  | Row tint rojo oscuro, mensaje aparece            |
| Toast           | Aparece bottom-right, fade out a 2.8s            |
| Tab switch      | Instantáneo (CustomTkinter)                      |
| Cover load      | Placeholder ♪ → imagen real (async)              |

---

## 10. ICONOGRAFÍA (Unicode)

| Símbolo | Uso                    |
|---------|------------------------|
| ♪       | Placeholder portada    |
| ↓       | Descargas nav item     |
| ⚙       | Ajustes nav item       |
| 🔍      | Buscar nav item        |
| ◈       | Dashboard nav item     |
| ≡       | Historial nav item     |
| ✓       | Éxito / añadido        |
| ✕       | Error / cerrar         |
| ＋      | Añadir a cola          |
| ←→      | Paginación historial   |
| ·       | Animación carga        |
| ↳       | Subruta (path/error)   |
| ▌       | Indicador nav activo   |

---

## 11. UX RECOMENDACIONES PARA DJS

1. **Búsqueda rápida**: Ctrl+F desde cualquier panel → foco en buscador.
2. **Añadir múltiples**: el botón ＋ se desactiva tras el primer clic para evitar duplicados.
3. **Queue visible siempre**: badge en sidebar muestra activos en tiempo real.
4. **Título de ventana dinámico**: "DJ Tracks · 3 descargando..." durante descargas.
5. **Path del archivo**: visible en cada fila completada para abrir directamente.
6. **Escape limpia búsqueda**: comportamiento estándar de apps pro.
7. **Renderizado por lotes**: playlists de 300+ tracks sin freeze.
8. **Tema cambiable en vivo**: sin reiniciar la app.
9. **Historial persistente**: sobrevive reinicios, exportable a CSV/JSON.
10. **Diagnósticos en status bar**: qué APIs están configuradas y cuáles no.
