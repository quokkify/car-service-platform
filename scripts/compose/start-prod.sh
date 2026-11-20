#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f .env ]]; then
  echo "Error: .env file not found."
  echo "Create it from template:"
  echo "  cp .env.example .env"
  exit 1
fi

set -a
source .env
set +a

# Fail closed: the production-like stack must not run with template placeholders or dev settings.
# Django enforces the same for DJANGO_SECRET_KEY / DJANGO_DEBUG; this check only gives an earlier, clearer error.
lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
prod_env_errors=0
prod_env_error() {
  echo "Error: $1" >&2
  prod_env_errors=$((prod_env_errors + 1))
}

case "$(lower "${DJANGO_DEBUG:-False}")" in
  true | 1 | yes) prod_env_error "DJANGO_DEBUG must be False for the production-like stack (development: bash scripts/compose/start.sh)." ;;
esac

secret_key="${DJANGO_SECRET_KEY:-}"
if [[ ${#secret_key} -lt 50 ]] || [[ "$(lower "${secret_key}")" =~ (change-?me|insecure|placeholder|replace-me|your-secret) ]]; then
  prod_env_error "DJANGO_SECRET_KEY must be a random value of at least 50 characters, e.g.: python3 -c \"import secrets; print(secrets.token_urlsafe(50))\""
fi

postgres_password="${POSTGRES_PASSWORD:-}"
if [[ -z "${postgres_password}" || "${postgres_password}" == "car_service_platform" || "$(lower "${postgres_password}")" =~ change-?me ]]; then
  prod_env_error "POSTGRES_PASSWORD must be set to a unique value (it is empty or a template placeholder)."
fi

for var_name in ADMIN_PASSWORD STAFF_PASSWORD; do
  case "$(lower "${!var_name:-}")" in
    admin12345 | staff12345 | admin | password | change-me* | changeme)
      prod_env_error "${var_name} is a known default password; set a unique strong password or leave it empty." ;;
  esac
done

if [[ ${prod_env_errors} -gt 0 ]]; then
  echo "Refusing to start the production-like stack: fix the values above in .env." >&2
  exit 1
fi

export GIT_COMMIT
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

if docker compose ps db | grep -q "Up"; then
  bash "${ROOT_DIR}/scripts/db/db-backup.sh" || true
fi

# Match CI (.github/actions/compose-up): BuildKit + Compose uses `docker build` with the current buildx builder (default on Docker Desktop).
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

docker compose up -d --build

echo ""
echo "${COMPOSE_PROJECT_NAME:-car-service-platform} is up:"
echo "  Frontend : http://localhost:${FRONTEND_PORT:-4173}"
echo "  Backend  : http://127.0.0.1:${BACKEND_PORT:-8000} (loopback only)"
echo "  Admin    : http://localhost:${FRONTEND_PORT:-4173}/admin/"
