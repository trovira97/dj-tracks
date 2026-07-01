# Terms of Service — DJ Tracks

**Última actualización:** 2026-06-23

Estos términos regulan el uso de:

- La aplicación de escritorio **DJ Tracks** distribuida desde
  [github.com/trovira97/dj-tracks](https://github.com/trovira97/dj-tracks/releases).
- El bot de Discord **DJ Tracks Bot** operado en el servidor oficial
  [DJ Tracks Community](https://discord.gg/cNkh8Yd2A7).
- El backend HTTPS asociado (`dj-tracks-trovira97.fly.dev`).

En conjunto, "el Servicio". Al usar cualquier parte del Servicio aceptas estos términos.

Si no estás de acuerdo con alguna parte, **no uses el Servicio**.

## 1. Elegibilidad

- Debes tener al menos **13 años** (o la edad mínima para usar Discord en tu jurisdicción, si es mayor).
- Debes cumplir con los [Términos de Servicio de Discord](https://discord.com/terms) y sus [Directrices Comunitarias](https://discord.com/guidelines).
- No puedes usar el Servicio si estás sujeto a sanciones aplicables (OFAC, UE, etc.).

## 2. Uso legítimo

DJ Tracks es una herramienta que **automatiza** descargas desde APIs públicas y `yt-dlp`.

**Tu responsabilidad**:
- Cumplir con las condiciones de servicio de cada plataforma que uses (Spotify, Apple Music, SoundCloud, Bandcamp, YouTube, Ko-fi).
- Cumplir con la legislación de copyright y derechos conexos de tu país.
- **No descargar música de la que no tengas derecho a obtener una copia.**

Los autores del Servicio **no somos responsables** del uso que hagas de la herramienta.

## 3. Comportamiento prohibido

Al usar el Servicio te comprometes a **no**:

- Distribuir descargas obtenidas con la app a terceros sin licencia.
- Usar el bot para spam, acoso, o para vulnerar el ToS de Discord.
- Intentar comprometer el backend (`fly.dev`), sus endpoints, o sus datos.
- Automatizar el uso del Servicio para consumir recursos de forma abusiva.
- Suplantar la identidad de otras personas (falsificar donaciones, IDs, etc.).
- Redistribuir versiones modificadas de la app pretendiéndolas oficiales.

Podemos suspender tu acceso — incluido el rol Donor si aplica — ante cualquier incumplimiento.

## 4. Modelo freemium

El Servicio incluye un tier gratuito y un tier Donor:

- **Free**: hasta 10 descargas por instalación. Contador gestionado por el backend.
- **Donor**: acceso ilimitado tras una donación única vía [Ko-fi](https://ko-fi.com/trovira_97) o asignación manual del rol por el administrador.

El rol Donor:
- Se otorga **una sola vez** por donación.
- **No es reembolsable** (donaciones voluntarias por Ko-fi).
- Puede revocarse si detectamos actividad fraudulenta o incumplimiento de los términos.
- No es transferible entre cuentas de Discord.

## 5. Bot de Discord

El bot **DJ Tracks Bot**:

- Sólo procesa comandos enviados por DM (`!donate`, `!fixrole`, `!help`).
- Sólo responde en el contexto del servidor oficial DJ Tracks.
- **No** guarda el contenido de tus mensajes más allá de lo estrictamente necesario para responder al comando.
- Recibe eventos `on_member_update` sólo para mantener sincronizado el rol Donor.
- No envía DMs no solicitados salvo notificar la asignación del rol.

## 6. Datos y privacidad

Ver la **[Política de Privacidad](./PRIVACY_POLICY.md)** para el detalle.

Resumen: guardamos tu **Discord User ID** (público en Discord), opcionalmente tu **email registrado en Discord** (sólo si vinculas cuenta vía OAuth), y las **donaciones que hagas** (email + importe + fecha). No vendemos datos, no hacemos tracking, no compartimos con terceros publicitarios.

## 7. Software de terceros

DJ Tracks usa las siguientes herramientas open source cuyos términos también aplican:

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — descarga real de audio.
- [spotdl](https://github.com/spotDL/spotify-downloader) — engine Spotify.
- [FFmpeg](https://ffmpeg.org/legal.html) — conversión de audio.
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter), [Pillow](https://pillow.readthedocs.io/), [mutagen](https://mutagen.readthedocs.io/) y otras librerías Python (ver `requirements.txt`).

## 8. Sin garantía

El Servicio se proporciona **"tal cual"**, sin garantía de ningún tipo. Puede fallar, tener bugs, sufrir cortes o desaparecer. No garantizamos:

- Que las plataformas soportadas sigan funcionando (yt-dlp puede romperse por cambios en YouTube, etc.).
- Que el backend esté disponible el 100% del tiempo.
- Que las descargas mantengan cualquier calidad específica.
- Que el rol Donor se preserve indefinidamente si migramos o cerramos el proyecto.

## 9. Limitación de responsabilidad

En la máxima medida permitida por la ley, los autores **no seremos responsables** de:

- Daños indirectos, incidentales, especiales o consecuentes.
- Pérdida de datos, ingresos, reputación u oportunidades.
- Uso indebido de la herramienta por parte de terceros.
- Consecuencias legales de tu uso del Servicio.

## 10. Cambios en los términos

Podemos actualizar estos términos en cualquier momento. Los cambios importantes se anunciarán en:

- El [server de Discord](https://discord.gg/cNkh8Yd2A7).
- El [CHANGELOG del repo](https://github.com/trovira97/dj-tracks/blob/main/CHANGELOG.md).

Al seguir usando el Servicio tras un cambio, aceptas la versión nueva.

## 11. Terminación

Puedes dejar de usar el Servicio en cualquier momento — desinstala la app, deja el server de Discord.

Podemos cerrar tu acceso si:

- Incumples estos términos.
- El proyecto entero se descontinúa (te avisaremos con antelación razonable si es posible).

## 12. Ley aplicable

Estos términos se rigen por la ley española (jurisdicción del autor). Cualquier disputa se resolverá en los tribunales de España.

## 13. Contacto

- Email: thibaudrovira1997@gmail.com
- Discord: [server oficial](https://discord.gg/cNkh8Yd2A7)
- Issues: [github.com/trovira97/dj-tracks/issues](https://github.com/trovira97/dj-tracks/issues)
