#!/bin/sh
set -e
envsubst '${BACKEND_URL} ${PORT}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

# Optional: trust X-Real-IP from an upstream proxy (comma-separated CIDRs), e.g. Railway's edge, which overwrites it.
realip_conf=/etc/nginx/conf.d/00-real-ip.conf
rm -f "${realip_conf}"
if [ -n "${NGINX_TRUSTED_REAL_IP_FROM:-}" ]; then
  echo "real_ip_header X-Real-IP;" > "${realip_conf}"
  for cidr in $(echo "${NGINX_TRUSTED_REAL_IP_FROM}" | tr ',' ' '); do
    echo "set_real_ip_from ${cidr};" >> "${realip_conf}"
  done
fi

exec nginx -g 'daemon off;'
