# Discord Server Blueprint — DJ Tracks Community

Este es el diseño completo del servidor: roles, categorías, canales, permisos, onboarding y automatizaciones. Está pensado para que se sienta como una comunidad **profesional** (tipo Beatport / open-source techie) desde el minuto uno.

Ejecútalo de arriba abajo en el orden que aparece — cada paso construye sobre el anterior.

---

## 1. Ajustes globales del server

**Server Settings → Overview**
- **Nombre:** `DJ Tracks`
- **Región del sistema:** Europe West (mejor latencia para tu público hispano)
- **AFK Voice Channel:** `Zzz · AFK` (5 min timeout — lo creamos abajo)
- **AFK Timeout:** 5 minutos
- **System Messages Channel:** `#👋-bienvenida`
- **Boost progress bar:** ON — motiva a la gente a boostear

**Server Settings → Moderation → Verification Level**
- **Medium** — usuarios deben tener email verificado en Discord + estar registrados hace más de 5 min. Filtra bots de spam sin frenar a usuarios legítimos.

**Server Settings → Moderation → Explicit Media Content Filter**
- **Scan media from all members**

**Server Settings → Moderation → Raid Protection**
- **Activation: ON** con configuración por defecto

**Server Settings → Community**
- **Enable Community** ON — desbloquea:
  - Onboarding
  - Welcome screen
  - Server discovery (cuando crezcas)
  - Announcement channels
  - Stage channels
  - Server Insights

---

## 2. Jerarquía de roles

Crear en Server Settings → Roles, **en este orden** (Discord ordena por creación, luego reordenas):

| Orden | Rol | Color | Permisos globales | ¿Cómo se otorga? |
|---|---|---|---|---|
| 1 (top) | 👑 **Owner** | Cyan `#00C8FF` | Administrator | Sólo tú |
| 2 | 🛡️ **Moderador** | Rojo `#EF4444` | Kick, Ban, Manage Messages, Mute, Timeout | Manual (tu criterio) |
| 3 | 🤖 **DJ Tracks Bot** | Cyan `#00C8FF` | Manage Roles + Send Messages | Automático (ya lo tienes) |
| 4 | ✨ **Beta Tester** | Amarillo `#FACC15` | + acceso a `#beta-*` | Manual, cuando alguien ayude a testear |
| 5 | 🎧 **DJ Verified** | Morado `#A020FF` | Ninguno especial, decorativo | Manual, tras compartir 3+ sets |
| 6 | 💎 **Donor** | Verde neón `#00FFB9` | + acceso a canales `#donors-*` | **Automático** (asignado por el bot al donar) |
| 7 | 🐛 **Bug Hunter** | Naranja `#FF6B00` | Ninguno especial, decorativo | Manual, cuando alguien reporte un bug real |
| 8 (bottom) | `@everyone` | Gris (default) | Send Messages, Add Reactions, Change Nickname | Automático al unirse |

**Importante — arrastra estos roles PUR encima del `Donor`:**
- 👑 Owner
- 🛡️ Moderador
- 🤖 DJ Tracks Bot

Sin esto último, el bot no puede asignar el rol Donor (Discord no permite tocar roles superiores al del bot).

---

## 3. Categorías y canales

Estructura completa. **Iconos usan emojis** — copia-pega tal cual.

### 📢 INFORMACIÓN
Canales de sólo lectura para info esencial. Layout limpio, aparecen primero.

| Canal | Tipo | Permisos | Propósito |
|---|---|---|---|
| `#👋-bienvenida` | Texto | `@everyone`: Read only (Send Messages OFF) | Mensaje de bienvenida fijado, resumen de qué es el server. Auto-mensajes de sistema (joins). |
| `#📜-reglas` | Texto | `@everyone`: Read only | Reglas del server (ver plantilla abajo). |
| `#📢-anuncios` | **Announcement** | `@everyone`: Read only | Anuncios de nuevas versiones, cambios importantes. Follow-able desde otros servers. |
| `#🆕-changelog` | Texto | `@everyone`: Read only | Auto-post cuando publicas release en GitHub (via webhook — te dejo config abajo). |
| `#❓-faq` | Texto | `@everyone`: Read only | Preguntas frecuentes: Spotify keys, SmartScreen warning, cómo pegar el Discord ID en Ko-fi, etc. |

### 🎧 DJ TRACKS · Comunidad
Canales generales para la comunidad. Éstos son los más activos.

| Canal | Tipo | Permisos | Propósito |
|---|---|---|---|
| `#💬-general` | Texto | Público | Chat abierto, presentaciones, off-topic ligero. |
| `#🙋-ayuda` | Texto | Público (Send Messages ON para todos) | Pedir ayuda con la app, dudas de instalación, config, errores. |
| `#💡-ideas` | Texto | Público | Sugerencias de features nuevas. Reacciones para votar. |
| `#🐛-bugs` | Texto | Público | Bug reports (redirige a los issue templates de GitHub — pon un mensaje fijado). |
| `#🌐-off-topic` | Texto | Público | Todo lo que no sea sobre DJ Tracks. Válvula de escape social. |

### 🎵 MÚSICA · Comparte y descubre
Canales para el nicho DJ real.

| Canal | Tipo | Permisos | Propósito |
|---|---|---|---|
| `#🎶-descubrimientos` | Texto | Público | Comparte tracks nuevos que hayas encontrado. |
| `#🎧-mis-sets` | Texto | Público (Slowmode 1h) | Postea tu set / mixtape reciente. Slowmode para evitar spam autopromo. |
| `#📀-playlists` | Texto | Público | Comparte playlists Spotify/Apple/SoundCloud. |
| `#🔥-wip` | Texto | Público (Slowmode 30 min) | Work in Progress — muéstranos tus producciones/edits. |
| `#🎤-request` | Texto | Público | "¿Cómo se llama esta canción?" — resolución colaborativa de tracks. |

### 💎 DONORS · Acceso exclusivo
Sólo visible para el rol `Donor`. Sensación de pertenencia real.

**Configuración de permisos de la categoría entera:**
- `@everyone`: **View Channel OFF**
- `💎 Donor`: **View Channel ON**
- `🛡️ Moderador` + `👑 Owner`: **View Channel ON**

| Canal | Tipo | Propósito |
|---|---|---|
| `#🎉-donors-only` | Texto | Chat exclusivo para donantes. |
| `#💾-beta-downloads` | Texto | Enlaces a builds beta antes de release oficial. |
| `#🔮-roadmap` | Texto | Discusión del roadmap privado, features next. |
| `#🎁-perks` | Texto | Cupones / recursos / packs exclusivos que consigas. |
| `#☕-thank-you` | Texto | Mensajes de agradecimiento fijados con el nombre de cada donante. |

### 🛠️ DEV · Público técnico
Para gente curiosa técnicamente. Público, pero se siente "insider".

| Canal | Tipo | Permisos | Propósito |
|---|---|---|---|
| `#⚙️-desarrollo` | Texto | Público | Discusión técnica: nuevas features, decisiones de arquitectura. |
| `#🧪-beta-testing` | Texto | Sólo `Beta Tester` + arriba | Coordinación de testing pre-release. |
| `#🔗-github-feed` | Texto | Público (read only) | Webhook GitHub: commits, releases, issues nuevos. |
| `#💻-plugins` | Texto | Público | Discusión sobre plugins/extensiones futuras. |

### 🎙️ VOZ
Canales de voz para eventos, jam sessions, watchalongs.

| Canal | Tipo | Permisos | Propósito |
|---|---|---|---|
| `🔊 General` | Voz | Público | Voz general. |
| `🎧 Music Chill` | Voz | Público, Music priority ON | Escuchar música juntos. Push-to-talk sugerido. |
| `📺 Streaming` | Stage | Público | Cuando hagas AMA / demo streams. |
| `🎤 DJ Booth` | Voz | `DJ Verified` + arriba | Espacio para DJs que compartan sesiones en vivo. |
| `🔇 Zzz · AFK` | Voz | Auto-move | AFK channel. |

### 🔒 STAFF (privado)
No visible para `@everyone`. Sólo Mods + Owner.

**Configuración de permisos de la categoría entera:**
- `@everyone`: **View Channel OFF**
- `🛡️ Moderador`: **View Channel ON**
- `👑 Owner`: **View Channel ON**

| Canal | Tipo | Propósito |
|---|---|---|
| `#🛡️-mod-chat` | Texto | Coordinación entre mods. |
| `#📋-mod-log` | Texto | Log automatizado de acciones de moderación (con bot como Wick o Dyno). |
| `#🔒-secretos` | Texto | Discusiones sensibles: revocaciones, disputas. |

---

## 4. Onboarding (Discord Community Onboarding)

**Server Settings → Onboarding**

### Bienvenida
- **Title:** `¡Bienvenido a DJ Tracks!`
- **Description:** `La comunidad oficial de la app de descargas para DJs. Aquí encuentras soporte, comparte tus tracks, propone ideas y — si donas — accedes al canal exclusivo de donantes.`

### Canales sugeridos
Marca estos como "recomendados" para nuevos usuarios:
- `#👋-bienvenida`
- `#📜-reglas`
- `#🙋-ayuda`
- `#💬-general`

### Preguntas de onboarding
Configura estas 3 preguntas para etiquetar automáticamente a los recién llegados.

**Pregunta 1:** `¿En qué modo usas DJ Tracks?`
Multi-select, no crea roles. Opciones:
- 🎧 Soy DJ profesional/semi-pro
- 🎉 Uso para fiestas / eventos
- 🎵 Sólo descargas personales
- 🔧 Me interesa el aspecto técnico

**Pregunta 2:** `¿Qué te trae al server?`
Multi-select. Opciones:
- 🙋 Necesito ayuda con la app
- 💡 Tengo ideas / feedback
- 🎶 Compartir música
- 💎 Ya doné (asigna rol `Donor` — **importante:** deja esto en modo "informativo", el rol lo asigna el bot, no la onboarding)
- 🐛 Reportar bugs

**Pregunta 3:** `¿Te interesa recibir notificaciones de…?`
Multi-select. Opciones → asigna roles opt-in:
- 📢 Anuncios de nuevas versiones → rol `Notif · Releases`
- 🎉 Eventos y streams → rol `Notif · Eventos`

Esos roles de notificación los creas aparte (color muted, permisos ninguno, sólo son mentiones opt-in).

---

## 5. Welcome Screen

**Server Settings → Community → Welcome Screen**

- **Descripción:** `Descarga música desde Spotify, Apple, SoundCloud, Bandcamp y YouTube con metadatos Beatport completos.`
- **Enlaces destacados** (máximo 5):
  1. `#📜-reglas` — Léelas primero
  2. `#🙋-ayuda` — ¿Problemas con la app?
  3. `#💬-general` — Preséntate a la comunidad
  4. `#🎶-descubrimientos` — Comparte tracks
  5. `https://ko-fi.com/trovira_97` — Apoya el proyecto

---

## 6. Mensajes fijados clave

### `#👋-bienvenida` (fijado)

```
🎧 ¡Bienvenido a DJ Tracks!

Somos la comunidad de la app open-source para descargar música con metadatos Beatport (BPM, key, Camelot). Aquí puedes:

✅ Pedir ayuda con la app
✅ Reportar bugs / sugerir features
✅ Compartir tracks y sets
✅ Acceder al canal exclusivo si donas

⚡ Empieza por leer las #📜-reglas y pasarte por #🙋-ayuda si tienes dudas.

📦 Descarga la última versión: https://github.com/trovira97/dj-tracks/releases/latest
☕ Apoya el proyecto: https://ko-fi.com/trovira_97
```

### `#📜-reglas` (fijado)

```
📜 REGLAS DE LA COMUNIDAD

1. Respeto ante todo
   No toleramos insultos, acoso, racismo, sexismo, homofobia ni discurso de odio.

2. Nada de piratería a la vista
   La app se usa para casos legítimos. No compartas material bajo copyright
   ni links de descarga ilegales aquí. Este server no es un pirate bay.

3. No spam ni autopromoción agresiva
   Compartir tu música es bienvenido en los canales musicales.
   Autopromo constante o publicidad de otras cosas está prohibida.

4. Un canal, un tema
   Cada canal tiene su propósito. Léelo en la descripción del canal antes
   de postear.

5. NSFW no
   Este es un server general. Contenido explícito no cabe aquí.

6. Nada de DMs no solicitados
   No hagas cold DMs para vender o promocionar cosas. Si alguien lo hace,
   avisa a un @🛡️ Moderador.

7. Cumple el ToS de Discord
   https://discord.com/terms

⚡ Incumplimiento = warning → mute → kick → ban, según la gravedad.
Si tienes dudas, pregunta a un @🛡️ Moderador antes de asumir.
```

### `#❓-faq` (fijado)

```
❓ PREGUNTAS FRECUENTES

▪️ SmartScreen me avisa al abrir el .exe
Es normal — la app no está firmada digitalmente todavía.
"Más información" → "Ejecutar de todas formas".

▪️ ¿Cómo dono para desbloquear la app?
Escríbele !donate <€> al bot DJ Tracks Bot por DM.
Te devuelve un enlace Ko-fi con tu Discord ID listo para pegar.

▪️ Doné pero no tengo el rol
- Espera 30 segundos y comprueba
- Si nada, escribe !fixrole al bot
- Si sigue sin funcionar, abre un ticket en #🙋-ayuda

▪️ ¿Cómo configuro Spotify?
Botón "❓ ¿Cómo configurar Spotify?" dentro de Ajustes en la app,
o mira la guía completa: https://github.com/trovira97/dj-tracks#-configuración-de-apis

▪️ ¿Es legal descargar de Spotify/Apple?
La app usa APIs públicas + yt-dlp. Tu responsabilidad es cumplir con
copyright y ToS de cada plataforma en tu jurisdicción.

▪️ La app se colgó / algo raro
- Ve al panel LOGS de la app
- Filtra por ERROR
- Copia y pega en #🐛-bugs con "@🛡️ Moderador" si es crítico
```

### `#🐛-bugs` (fijado)

```
🐛 CÓMO REPORTAR UN BUG

Los bugs se gestionan en GitHub Issues para no perderlos:
→ https://github.com/trovira97/dj-tracks/issues/new/choose

Copia estos datos en el issue (no aquí):

1. Versión de la app (Ajustes → arriba a la derecha, o v en la sidebar)
2. Sistema operativo (Windows 10/11/…)
3. Qué hiciste, paso a paso
4. Qué esperabas que pasase
5. Qué pasó en su lugar
6. Logs: panel LOGS de la app → filtra ERROR → 📋 Copiar todo → pega en el issue

Para dudas rápidas antes de abrir issue, pregunta en #🙋-ayuda.
```

---

## 7. Webhooks e integraciones

### GitHub → `#🆕-changelog` y `#🔗-github-feed`

1. En el server → click derecho en `#🔗-github-feed` → **Editar canal** → **Integraciones** → **Webhooks** → **Nuevo webhook** → cópialo.
2. En GitHub → tu repo `dj-tracks` → **Settings** → **Webhooks** → **Add webhook**:
   - Payload URL: pega el webhook de Discord **con `/github` añadido al final** (Discord hace ese magic para parsear GitHub bien)
   - Content type: `application/json`
   - Events: `Just the push event` (o "individual events" y marca releases, issues, PRs)
   - Active: ✓

Repite para `#🆕-changelog` pero sólo con evento `Release published`.

### Ko-fi → Discord (anuncios de donaciones)

Ko-fi tiene integración nativa opcional:
1. https://ko-fi.com/manage/integrations
2. **Discord integration** → conecta tu server DJ Tracks
3. Elige el canal `#🎉-donors-only` (o crea un `#🎉-nuevas-donaciones` público si prefieres presumir)
4. Personaliza el mensaje que aparece al donar

⚠️ **Ojo**: si eliges canal público, no muestres emails. Sólo nombre público del donante.

---

## 8. Server Boost — a qué aspirar

El objetivo realista: **7 boosts (Nivel 1)** para desbloquear:
- Emoji slots 50 (vs 50 base)
- Sticker slots 15 (vs 0 base)
- Audio quality 128kbps (mejor voz)
- Banner personalizado
- Vanity URL (por ejemplo `discord.gg/dj-tracks` — si está libre)

Cada boost cuesta 5€/mes. **Nivel 2 (14 boosts)** desbloquea:
- 300 emoji + 30 stickers
- 256kbps voz
- 50MB uploads para todos (útil para compartir clips)

Cuando llegues a 5-6 donantes activos, es realista pedir boosts entre ellos.

---

## 9. Bots recomendados (además del tuyo)

### Wick o Dyno — moderación
- **Auto-mod** contra links de invitación, palabras baneadas
- **Warn / mute / kick / ban** con log automático a `#📋-mod-log`
- **Anti-raid** (Wick tiene el mejor sistema)
- Setup: 10 min

### MEE6 o Statbot — engagement
- Sistema de niveles por participación (opcional — puede sentir "gamificado")
- Bienvenidas automáticas si no quieres usar el mensaje de sistema

### Reaction Roles (Carl-bot o Sesh)
- Para los roles opt-in de notificaciones (marca ✅ para el rol de anuncios)

**Mi recomendación mínima:** sólo Wick para moderación. Todo lo demás puede esperar hasta que crezca la comunidad.

---

## 10. Checklist de ejecución (orden estricto)

Márcalo mentalmente mientras vas haciéndolo:

- [ ] Habilitar Community en el server (Settings → Community)
- [ ] Ajustar Verification Level a Medium
- [ ] Activar Raid Protection + Media Content Filter
- [ ] Crear los 7 roles (Owner, Mod, Bot, Beta Tester, DJ Verified, Donor, Bug Hunter)
- [ ] Ordenar la lista de roles (arrastrar bot POR ENCIMA de Donor)
- [ ] Crear la categoría INFORMACIÓN + sus canales
- [ ] Crear categoría DJ TRACKS + canales
- [ ] Crear categoría MÚSICA + canales
- [ ] Crear categoría DONORS + canales + poner permisos privados
- [ ] Crear categoría DEV + canales
- [ ] Crear categoría VOZ + canales
- [ ] Crear categoría STAFF + canales + poner permisos privados
- [ ] Fijar los mensajes clave en `#👋-bienvenida`, `#📜-reglas`, `#❓-faq`, `#🐛-bugs`
- [ ] Configurar webhooks GitHub (2 canales)
- [ ] Configurar Onboarding con las 3 preguntas
- [ ] Configurar Welcome Screen con los 5 enlaces
- [ ] Instalar bot Wick para moderación
- [ ] Testear con una cuenta alternativa (o pide a un amigo) que el onboarding se ve OK

---

## 11. Comunidad primeros pasos

Cuando tengas todo montado:

1. **Post en `#📢-anuncios`**: presenta el server y la app v2.2.0.
2. **Invita a 3-5 gente cercana** primero para que el server no parezca vacío.
3. **Sube el link de invitación** a: GitHub README (ya está), Twitter/BlueSky/Instagram si tienes, Reddit r/DJs / r/Beatmatch (respetando sus reglas).
4. **Fija un post en `#💬-general`** presentándote y pidiendo que la gente se presente.
5. **Haz el primer streaming/AMA en `#📺-Streaming`** en 2-3 semanas para dar vida.

---

Ejecuta el checklist en el orden que aparece. Cuando termines dime y verifico contigo que todo cuadra desde una cuenta externa.
