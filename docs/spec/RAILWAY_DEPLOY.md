# Railway Deployment Guide

> Railway is the **staging/testing environment** for this project.
> The goal is to validate features and fixes before migrating to a permanent VPS.

## Architecture

Three Railway services in one project:

| Service | Root dir | Port | Domain |
|---------|----------|------|--------|
| backend | `backend/` | 8000 | `backend-production-9f32.up.railway.app` |
| frontend | `frontend/` | dynamic `$PORT` | `<your-app>.up.railway.app` |
| db | Railway PostgreSQL | 5432 | internal only |

Frontend nginx proxies `/api/` and `/media/` to backend over Railway's **private IPv6 network** (`backend.railway.internal`).

---

## First-time Setup

### 1. Create Railway project

Railway Dashboard → New Project → Empty Project.

### 2. Add PostgreSQL

New Service → Database → PostgreSQL. Note the values in its **Variables** tab — you will need them in step 5.

### 3. Add backend service

New Service → Empty Service → Settings → Source → connect GitHub repo, set **Root Directory** to `backend`.
Railway auto-detects `backend/railway.toml`.

### 4. Add frontend service

New Service → Empty Service → Settings → Source → connect same repo, set **Root Directory** to `frontend`.
Railway auto-detects `frontend/railway.toml`.

### 5. Set environment variables

**Backend service → Variables:**

```
DJANGO_SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_urlsafe(50))">
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=<backend-domain>.up.railway.app,healthcheck.railway.app
CORS_ALLOWED_ORIGINS=https://<frontend-domain>.up.railway.app
FRONTEND_URL=https://<frontend-domain>.up.railway.app

# Copy exact values from PostgreSQL service → Variables tab (reference vars may not resolve)
POSTGRES_DB=railway
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<from postgres service>
POSTGRES_HOST=<from postgres service>
POSTGRES_PORT=5432

PORT=8000
GUNICORN_WORKERS=2
GUNICORN_BIND=[::]:8000
# Required: shared, persistent rate-limit counters (table created on start)
DJANGO_CACHE_BACKEND=django.core.cache.backends.db.DatabaseCache
DJANGO_CACHE_LOCATION=django_cache

ADMIN_EMAIL=admin@yourdomain.com
ADMIN_PASSWORD=<strong-password>
STAFF_EMAIL=staff@yourdomain.com
STAFF_PASSWORD=<strong-password>

LOG_LEVEL=INFO
LOG_FORMAT=text
MEDIA_ROOT=/data/media
```

> **Important:** Railway reference variables (`${{Postgres.PGDATABASE}}`) may not resolve.
> Copy the actual values directly from the PostgreSQL service Variables tab.

> **Important:** `GUNICORN_BIND=[::]:8000` is required because Railway's private network
> routes inter-service traffic over IPv6. Without it nginx gets 504 timeouts.

**Frontend service → Variables:**

```
BACKEND_URL=http://backend.railway.internal:8000
PORT=80
NGINX_TRUSTED_REAL_IP_FROM=<edge address range, see "Client IP" below>
CORS_ALLOWED_ORIGINS=https://<frontend-domain>.up.railway.app
FRONTEND_URL=https://<frontend-domain>.up.railway.app
```

> **Secrets:** with `DJANGO_DEBUG=False` the backend refuses to start unless `DJANGO_SECRET_KEY` is a random
> value of at least 50 characters, and `seed_admin` / `seed_staff` refuse known default or weak passwords.
> `ADMIN_PASSWORD` / `STAFF_PASSWORD` only create missing accounts; rotate existing ones with
> `railway run python manage.py changepassword <email>` (or the Django admin).

#### Client IP

Railway documents `X-Real-IP` as the header identifying the client's address
([specs and limits](https://docs.railway.com/networking/public-networking/specs-and-limits)) but publishes no
edge address ranges and does not say whether a client-sent `X-Real-IP` is replaced. The frontend nginx uses
`X-Real-IP` only from peers in `NGINX_TRUSTED_REAL_IP_FROM` and forwards the result to Django
(`X-Real-IP`, `X-Forwarded-For`), which uses it for the login and customer-portal rate limits.

- On Railway the frontend **refuses to start** while `NGINX_TRUSTED_REAL_IP_FROM` is empty: every client would
  share the edge address, so the limits would apply to all users together.
- `0.0.0.0/0`, `::/0` (any `/0`) are rejected: trusting every peer would let clients pick their own address.

**Before relying on it (run this before the first Railway deploy of this version, and after Railway networking changes):**

1. Deploy the frontend with a value that trusts nothing, e.g. `NGINX_TRUSTED_REAL_IP_FROM=127.0.0.1/32`.
2. Run `curl -s -o /dev/null -H 'X-Real-IP: 203.0.113.9' https://<frontend-domain>/api/health` and find that
   request in the frontend service log. The first field is the edge peer address; the last quoted field is the
   `X-Real-IP` the edge delivered.
3. If the last field is **your own** address, the edge replaces the header: set `NGINX_TRUSTED_REAL_IP_FROM` to the
   narrowest range covering the edge peer addresses you see across a few requests and redeploy.
   If it is `203.0.113.9`, the edge passes client values through: keep `127.0.0.1/32` (limits are then shared by
   all users) and set `LOGIN_THROTTLE_KNOWN_SOURCE_SECONDS=0` on the backend, because a shared address would make
   every login look like it comes from a known source. The per-account login limit works either way.

### 6. Set custom domain (optional)

Frontend → Settings → Networking → edit the generated subdomain to your preferred name.
After renaming update `CORS_ALLOWED_ORIGINS` and `FRONTEND_URL` on the **backend** service.

### 7. Attach Volume (media files)

Backend service → Volumes → Add Volume → mount path: `/data/media`.
Persists uploaded PDFs/documents across redeploys (~$0.25/GB/month).

### 8. Link Railway CLI locally

```bash
npm install -g @railway/cli
railway login

cd backend
railway link   # select project → backend service

cd ../frontend
railway link   # select project → frontend service
```

---

## Deploying

```bash
# Full redeploy (backend + frontend)
bash scripts/deploy/deploy.sh

# Backend only
bash scripts/deploy/deploy.sh --backend-only

# Frontend only
bash scripts/deploy/deploy.sh --frontend-only
```

The script pushes `main` to GitHub then runs `railway up --detach` from each service directory.

---

## Startup sequence (automatic on each backend deploy)

1. `python manage.py migrate --noinput` — applies new DB migrations
2. `python manage.py createcachetable` — creates the cache table when `DatabaseCache` is configured (no-op otherwise)
3. `python manage.py collectstatic --noinput`
4. `python manage.py seed_admin` — creates admin account if missing; never changes an existing account
5. `python manage.py seed_staff` — creates staff account if missing; never changes an existing account
6. `gunicorn config.wsgi:application -c gunicorn.conf.py`

---

## Health checks

| Service | Endpoint | Timeout |
|---------|----------|---------|
| backend | `GET /api/health` | 300 s |
| frontend | `GET /` | 60 s |

---

## Database backup

```bash
# Get DATABASE_URL from PostgreSQL service → Variables tab
pg_dump "postgresql://postgres:<password>@<host>:<port>/railway" \
  --no-owner --no-acl -Fc -f backup.dump

# Restore to another server
pg_restore -d "postgresql://user:pass@host:5432/dbname" --no-owner backup.dump
```

---

## Troubleshooting

### Frontend returns 504 after backend redeploy

nginx resolves `backend.railway.internal` DNS at startup and caches the IP. When backend
gets a new container (redeploy), its internal IP changes — nginx still uses the old one.

**Fix:** redeploy frontend after backend:
```bash
bash scripts/deploy/deploy.sh --frontend-only
```

### `Invalid HTTP_HOST header: 'healthcheck.railway.app'`

Add `healthcheck.railway.app` to `DJANGO_ALLOWED_HOSTS` in backend Variables.

### gunicorn `Address already in use` on `[::]:8000`

Do not use `bind = ["0.0.0.0:8000", "[::]:8000"]` — it causes a conflict on Linux
because `[::]` already covers IPv4 via dual-stack. Use only `GUNICORN_BIND=[::]:8000`.

### nginx `io_setup() failed (Resource temporarily unavailable)`

Railway's seccomp policy blocks the Linux AIO syscall. Fixed via `frontend/nginx-main.conf`
which sets `aio off; sendfile off; worker_processes 1;`.

### nginx `send() failed (111: Connection refused) while resolving, resolver: 127.0.0.11`

`127.0.0.11` is Docker's embedded DNS — it is not available on Railway's Wireguard network.
Do not add a `resolver` directive to nginx.conf. nginx resolves `backend.railway.internal`
via the system resolver at startup, which works correctly on Railway.

---

## Rollback

Railway Dashboard → service → Deployments → previous deploy → Redeploy.

---

## Secrets

All production secrets live in the Railway Dashboard. Never commit them to the repository.
Deploy runs via Railway CLI — no webhook URLs or `.env.railway.local` file needed.
