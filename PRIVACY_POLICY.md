# Privacy Policy — DJ Tracks

**Última actualización:** 2026-06-23

Esta política describe qué datos recogemos, para qué los usamos y qué derechos tienes.

Se aplica a:

- La aplicación de escritorio **DJ Tracks**.
- El bot de Discord **DJ Tracks Bot**.
- El backend HTTPS `dj-tracks-trovira97.fly.dev`.

**Responsable del tratamiento**: Thibaud Rovira ([thibaudrovira1997@gmail.com](mailto:thibaudrovira1997@gmail.com)).

## 1. Qué datos recogemos

### 1.1 En la app de escritorio (local, en tu PC)

Se guardan **en tu ordenador**, nunca los enviamos a ningún servidor:

- Historial de descargas (nombre, artista, fecha).
- Configuración (rutas, calidad, credenciales de Spotify que tú introduces).
- Contador local de descargas (`usage.json`) y un `device_id` aleatorio generado en el primer arranque.
- Logs de la aplicación (`%APPDATA%\DJ Tracks\logs\`).
- Caché de Beatport y portadas.

### 1.2 En el backend (nuestro servidor en Fly.io)

Sólo guardamos lo estrictamente necesario para el flujo de donantes:

| Dato | Origen | Motivo |
|---|---|---|
| Discord User ID | Vínculo OAuth o pegado en Ko-fi | Verificar si eres donante |
| Discord username | Vínculo OAuth | Mostrar tu nombre en los mensajes del bot |
| Email de Discord (opcional) | Scope `email` del OAuth | Emparejar donaciones por email |
| Email de Ko-fi | Webhook de Ko-fi | Emparejar pagos con Discord |
| Importe de la donación | Webhook de Ko-fi | Registro contable |
| `device_id` | Generado por tu app | Contador anti-abuso |
| Contador de descargas | Generado por tu app | Freemium gate |

**No** guardamos:

- El contenido de los mensajes que envíes al bot (más allá del comando específico procesado).
- Datos de pago (Ko-fi los gestiona, nosotros sólo recibimos el email + importe).
- Historial de descargas ni las canciones que bajas.
- Direcciones IP más allá de logs efímeros del proxy Fly (retención ~30 días, no procesamos).
- Datos de otros servers de Discord donde el bot esté.

### 1.3 En Ko-fi

Cuando donas, [Ko-fi](https://ko-fi.com/privacy) gestiona tu pago según **su** política de privacidad. Nosotros sólo recibimos el email, importe, mensaje (si pegaste Discord ID) y timestamp vía su webhook.

### 1.4 En Discord

Cuando usas el bot, Discord gestiona el transporte según **su** política de privacidad. Nosotros vemos únicamente:

- Los DMs que envías al bot con los comandos.
- Los cambios de rol Donor en nuestro servidor (via `on_member_update`).

## 2. Para qué usamos tus datos

- **Ejecutar el freemium gate**: contador + verificación del rol Donor.
- **Emparejar donaciones**: vincular tu Discord con tu donación en Ko-fi.
- **Asignar el rol Donor** automáticamente cuando corresponda.
- **Responder a comandos del bot** (`!donate`, `!fixrole`, `!help`).
- **Notificarte** por DM cuando se te asigna el rol.
- **Depurar errores** en producción (logs efímeros, no personales).

**No usamos tus datos para**:

- Publicidad, ni propia ni de terceros.
- Perfilado o segmentación.
- Venta a terceros.
- Marketing sin tu consentimiento explícito.

## 3. Con quién compartimos datos

Sólo con los servicios estrictamente necesarios para operar:

- **Discord** — envío de mensajes, asignación de roles (limitado al server oficial).
- **Ko-fi** — recepción de webhooks de donaciones.
- **Fly.io** — hosting del backend (Frankfurt / París). Procesa datos como encargado en nuestro nombre.
- **GitHub** — hosting del código y las releases. No accede a datos de usuarios finales.

**Nunca** vendemos datos ni los cedemos a redes de publicidad.

## 4. Retención

- **Datos locales en tu PC**: viven mientras tengas la app instalada. Al desinstalar o borrar `%APPDATA%\DJ Tracks\` se van.
- **Datos en el backend**:
  - Registro de donante: **indefinido** mientras el proyecto exista, para mantener tu acceso.
  - Pending donations (email + importe sin vincular): **90 días**, luego se purgan.
  - Sesiones OAuth: **1 hora** (temporales durante el flujo de login).
- **Logs de servidor**: retención de Fly ~30 días, no leemos personalmente.

## 5. Tus derechos (RGPD si estás en la UE)

Puedes ejercer estos derechos en cualquier momento escribiendo a [thibaudrovira1997@gmail.com](mailto:thibaudrovira1997@gmail.com):

- **Acceso** — copia de los datos que tenemos sobre ti.
- **Rectificación** — corregir datos inexactos.
- **Supresión** — borrar tu registro (esto implica perder el rol Donor).
- **Portabilidad** — recibir tus datos en formato estructurado (JSON).
- **Oposición** — dejar de procesar tus datos (implica dejar de usar el servicio).
- **Reclamación** — ante la [AEPD](https://www.aepd.es/) si crees que hemos vulnerado tus derechos.

Responderemos en un máximo de **30 días**.

## 6. Base legal del tratamiento

- **Consentimiento** — al vincular Discord y donar aceptas el tratamiento descrito aquí.
- **Ejecución de contrato / interés legítimo** — mantener el rol Donor para quienes hayan donado.
- **Obligación legal** — conservar registros contables básicos de las donaciones.

## 7. Menores

El Servicio no está dirigido a menores de 13 años. Si crees que un menor ha proporcionado datos sin autorización, [avísanos](mailto:thibaudrovira1997@gmail.com) y los eliminaremos.

## 8. Cookies

El backend **no usa cookies**. No hay analítica web ni tracking pixels. La única "cookie" del flujo OAuth es el propio state token de Discord, efímero.

## 9. Seguridad

- Backend accesible sólo por **HTTPS** (Fly.io fuerza TLS).
- Secretos (bot token, Ko-fi verification, DB) en **variables de entorno** gestionadas por Fly Secrets, nunca en el repo.
- Base de datos SQLite en **volumen cifrado** de Fly.
- Webhook de Ko-fi validado con **verification_token** único.
- OAuth Discord usa **state token** para prevenir CSRF.

No podemos garantizar seguridad absoluta — ver la [SECURITY.md](./SECURITY.md) para reportar vulnerabilidades.

## 10. Transferencias internacionales

Nuestros servidores están en la UE (París). Discord y GitHub tienen sedes fuera de la UE (Estados Unidos) — se aplican las **cláusulas contractuales tipo** aprobadas por la Comisión Europea para transferencias internacionales.

## 11. Cambios en esta política

Publicaremos cualquier cambio en:

- Este archivo en el repositorio.
- El [server de Discord](https://discord.gg/cNkh8Yd2A7) si el cambio es material.

Al seguir usando el Servicio tras un cambio, aceptas la versión nueva.

## 12. Contacto

**Responsable**: Thibaud Rovira

- Email: [thibaudrovira1997@gmail.com](mailto:thibaudrovira1997@gmail.com)
- Discord: [server oficial](https://discord.gg/cNkh8Yd2A7) — @trovira97
- Correo postal: [omitido en la copia pública; disponible bajo petición formal]
