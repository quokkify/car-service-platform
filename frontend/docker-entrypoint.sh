#!/bin/sh
set -e
envsubst '${BACKEND_URL} ${PORT}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

# Trust X-Real-IP only from the listed upstream proxy addresses (comma-separated CIDRs), e.g. Railway's edge.
# See docs/spec/RAILWAY_DEPLOY.md, "Client IP".
realip_conf=/etc/nginx/conf.d/00-real-ip.conf
rm -f "${realip_conf}"
trusted="${NGINX_TRUSTED_REAL_IP_FROM:-}"

if [ -z "${trusted}" ] && [ -n "${RAILWAY_ENVIRONMENT:-}" ]; then
  echo "ERROR: NGINX_TRUSTED_REAL_IP_FROM must be set on Railway. Without it every client shares the edge address," >&2
  echo "so login and portal rate limits would apply to all users together." >&2
  echo "Set it to the edge address range as described in docs/spec/RAILWAY_DEPLOY.md, section \"Client IP\"." >&2
  exit 1
fi

if [ -n "${trusted}" ]; then
  echo "real_ip_header X-Real-IP;" > "${realip_conf}"
  for cidr in $(echo "${trusted}" | tr ',' ' '); do
    case "${cidr}" in
      */0 | 0.0.0.0 | ::)
        echo "ERROR: NGINX_TRUSTED_REAL_IP_FROM must not contain '${cidr}': trusting every peer lets clients choose" >&2
        echo "their own X-Real-IP. List only the upstream proxy range (docs/spec/RAILWAY_DEPLOY.md, \"Client IP\")." >&2
        exit 1
        ;;
    esac
    echo "set_real_ip_from ${cidr};" >> "${realip_conf}"
  done
fi

exec nginx -g 'daemon off;'
