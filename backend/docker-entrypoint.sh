#!/bin/sh
set -e

# A bind-mounted ./data may be owned by root (older versions ran as root) or by the
# host user. Make it writable for the unprivileged app user, then drop privileges.
if [ "$(id -u)" = "0" ]; then
  chown -R app:app "${DATA_DIR:-/app/data}" 2>/dev/null || true
  exec setpriv --reuid=app --regid=app --init-groups "$@"
fi
exec "$@"
