# Security Policy

## Reporte privado de vulnerabilidades

Si encuentras una vulnerabilidad de seguridad — **no la abras como issue público**.

Avísame por canal privado:

- 📧 Email: thibaudrovira1997@gmail.com
- 💬 DM en Discord: trovira97 (en el [server](https://discord.gg/cNkh8Yd2A7))

Intentaré responder en menos de 72 h, parchear en cuanto sea posible y
publicar un fix con crédito al reporter (si lo desea).

## Áreas sensibles

Las partes del proyecto que más atención merecen:

- **`backend/`** — el servicio FastAPI desplegado en Fly.io. Endpoints
  públicos (`/verify`, `/discord/start`, `/kofi-webhook`, `/usage/*`).
  Maneja datos personales mínimos (Discord ID, email opcional) y
  emite role-grants en un servidor de Discord.
- **`utils/donor_gate.py`** — el gate freemium. Cualquier bug aquí
  decide quién accede a la app.
- **Webhooks Ko-fi** — validados por `KOFI_VERIFICATION_TOKEN`.
- **OAuth Discord** — flujo `identify` + `email` scope.
- **Auto-update** — descarga y ejecuta binarios desde GitHub Releases.
  Si comprometen mi cuenta, los usuarios pueden recibir un .exe falso.
  Mitigación pendiente: code signing (en roadmap).

## Lo que NO consideramos vulnerabilidad

- **Bypassear el gate freemium modificando el código fuente local**.
  El repo es open source. Honestamente: si estás en este apartado
  buscando saltarte el límite, la propia honestidad de tu acción
  ya responde la pregunta. El gate es honour-system para el 99% de
  usuarios — quien lo rompa, no es nuestra prioridad.
- **Reportes automatizados de scanners** sin contexto humano.

## Versiones soportadas

| Versión | Soporte |
|---------|---------|
| 2.2.x   | ✅      |
| 2.1.x   | ❌ (upgrade via auto-update) |
| < 2.1   | ❌      |
