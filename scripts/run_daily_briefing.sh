#!/bin/sh
# Cron-safe runner for the daily Know Today briefing.
set -eu

PROJECT_ROOT="/Users/juha/Desktop/projects/know-today"
SSH_KEY="/Users/juha/.ssh/know_today_pi"
PROXY_PORT="1080"

export PATH="/Users/juha/.local/bin:/usr/local/bin:/usr/bin:/bin"
export KNOW_TODAY_HTTP_PROXY="socks5h://127.0.0.1:${PROXY_PORT}"
export KNOW_TODAY_HTTPS_PROXY="$KNOW_TODAY_HTTP_PROXY"

# Recreate the private Tailscale tunnel after a reboot if it is not already up.
if ! /usr/sbin/lsof -nP -iTCP:"$PROXY_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  /usr/bin/ssh -f -N -D "127.0.0.1:${PROXY_PORT}" \
    -i "$SSH_KEY" \
    -o IdentitiesOnly=yes \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    knowtoday@know-today-pi
fi

cd "$PROJECT_ROOT"
exec "$PROJECT_ROOT/.venv/bin/python" scripts/generate_youtube_briefing.py
