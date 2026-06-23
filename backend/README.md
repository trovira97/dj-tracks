# DJ Tracks Backend

Pequeño servicio FastAPI que vincula donaciones de Ko-fi → rol de Discord
y expone un endpoint que la app desktop consulta para saber si un usuario
es donante.

## Endpoints

| Método | Ruta | Para qué |
|---|---|---|
| GET | `/` | Health check |
| GET | `/verify?discord_id=…` | "¿Este usuario tiene el rol Donor?" |
| GET | `/discord/start?token=…` | Inicia OAuth con Discord (redirige) |
| GET | `/discord/callback` | Discord vuelve aquí tras autorizar |
| GET | `/discord/poll?token=…` | La app pollea esto hasta obtener el resultado |
| POST | `/kofi-webhook` | Ko-fi notifica una donación → asignamos rol |

## Variables de entorno

Copia `.env.example` → `.env` y rellena:

```
DISCORD_CLIENT_ID         # OAuth2 → Client ID
DISCORD_CLIENT_SECRET     # OAuth2 → Client Secret
DISCORD_BOT_TOKEN         # Bot → Token (NO lo subas a git)
DISCORD_GUILD_ID          # Server ID
DISCORD_DONOR_ROLE_ID     # Role ID del rol "Donor"
DISCORD_REDIRECT_URI      # http://localhost:8732/discord/callback (dev) / https://… (prod)
KOFI_VERIFICATION_TOKEN   # Ko-fi → Account → API → Verification token
```

## Local dev

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
cp .env.example .env                                # rellena los valores
uvicorn app:app --port 8732 --reload
```

Comprueba:
- `curl http://localhost:8732/` → `{"ok": true, ...}`
- `curl "http://localhost:8732/verify?discord_id=TUDISCORDID"` → `{"donor": false}`

## Deploy

### Fly.io (recomendado — free tier suficiente)

```bash
fly launch                            # genera fly.toml
fly secrets set DISCORD_CLIENT_ID=… DISCORD_CLIENT_SECRET=… \
                DISCORD_BOT_TOKEN=… DISCORD_GUILD_ID=… \
                DISCORD_DONOR_ROLE_ID=… KOFI_VERIFICATION_TOKEN=…
fly deploy
```

Luego actualiza:
- En Discord Developer Portal → OAuth2 → Redirects: añade
  `https://<tu-app>.fly.dev/discord/callback`
- Variable `DISCORD_REDIRECT_URI` con la misma URL
- En Ko-fi → Webhook URL: `https://<tu-app>.fly.dev/kofi-webhook`
- En la app desktop, `config/settings.json` → `backend_url`:
  `https://<tu-app>.fly.dev`

### Railway

Similar — `railway init`, `railway variables set …`, `railway up`.

## Storage

SQLite local (`donors.db`).  Para tier free de Fly/Railway con disco
efímero, monta un volumen persistente o migra a Postgres.  Para volumen
de donaciones bajo (cientos al año) SQLite + volumen va sobrado.
