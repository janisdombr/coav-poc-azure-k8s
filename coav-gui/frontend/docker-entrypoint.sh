#!/bin/sh
set -e
# Substitute only ${BACKEND_URL} — nginx variables ($uri, $scheme, etc.) are left intact
envsubst '${BACKEND_URL}' < /etc/nginx/nginx.conf.template > /etc/nginx/conf.d/default.conf
echo "[nginx] Backend URL: ${BACKEND_URL}"
