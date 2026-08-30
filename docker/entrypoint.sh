#!/bin/sh
# Honor Unraid-style PUID/PGID for /data ownership, then drop privileges.
set -e
PUID="${PUID:-99}"
PGID="${PGID:-100}"

mkdir -p /data
if [ "$(id -u)" = "0" ]; then
    chown -R "$PUID:$PGID" /data 2>/dev/null || true
    exec gosu "$PUID:$PGID" "$@"
fi
exec "$@"
