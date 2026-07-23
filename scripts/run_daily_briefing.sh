#!/usr/bin/env bash
# One-shot, scheduler-safe runner for the daily Know Today briefing.
set -euo pipefail

RUN_HOUR="${KNOW_TODAY_RUN_HOUR:-9}"
RUN_MINUTE="${KNOW_TODAY_RUN_MINUTE:-0}"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
SSH_KEY="/Users/juha/.ssh/know_today_pi"
PROXY_PORT="1080"
STATE_FILE="$PROJECT_ROOT/output/youtube/daily-runner.state"
LOCK_DIR="$PROJECT_ROOT/output/youtube/daily-runner.lock"

export PATH="/Users/juha/.local/bin:/usr/local/bin:/usr/bin:/bin"
export KNOW_TODAY_HTTP_PROXY="socks5h://127.0.0.1:${PROXY_PORT}"
export KNOW_TODAY_HTTPS_PROXY="$KNOW_TODAY_HTTP_PROXY"

if ! [[ "$RUN_HOUR" =~ ^([01]?[0-9]|2[0-3])$ ]] || ! [[ "$RUN_MINUTE" =~ ^[0-5]?[0-9]$ ]]; then
  echo "Error: KNOW_TODAY_RUN_HOUR must be 0-23 and KNOW_TODAY_RUN_MINUTE must be 0-59."
  exit 1
fi

datetime_to_epoch() {
  python3 -c 'from datetime import datetime; import sys, time; value = datetime.strptime(sys.argv[1], "%Y-%m-%d %H:%M:%S"); print(int(time.mktime(value.timetuple())))' "$1"
}

read_state_value() {
  local key="$1"
  [[ -f "$STATE_FILE" ]] || return 0
  awk -F= -v key="$key" '$1 == key { print substr($0, length(key) + 2); exit }' "$STATE_FILE"
}

write_state() {
  local last_success="$1" last_attempt="$2" last_error="$3" temp_file
  mkdir -p "$(dirname "$STATE_FILE")"
  temp_file=$(mktemp "$PROJECT_ROOT/output/youtube/daily-runner.state.XXXXXX")
  {
    printf 'last_success=%s\n' "$last_success"
    printf 'last_attempt=%s\n' "$last_attempt"
    printf 'last_error=%s\n' "$last_error"
  } > "$temp_file"
  mv "$temp_file" "$STATE_FILE"
}

acquire_lock() {
  local lock_pid
  mkdir -p "$(dirname "$LOCK_DIR")"
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" > "$LOCK_DIR/pid"
    return
  fi

  lock_pid=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
  if [[ "$lock_pid" =~ ^[1-9][0-9]*$ ]] && kill -0 "$lock_pid" 2>/dev/null; then
    echo "Another Know Today briefing run is already active (PID: $lock_pid); skipping."
    exit 0
  fi

  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR"
  printf '%s\n' "$$" > "$LOCK_DIR/pid"
}

ensure_proxy_tunnel() {
  if /usr/sbin/lsof -nP -iTCP:"$PROXY_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    return
  fi

  /usr/bin/ssh -f -N -D "127.0.0.1:${PROXY_PORT}" \
    -i "$SSH_KEY" \
    -o BatchMode=yes \
    -o ConnectTimeout=20 \
    -o IdentitiesOnly=yes \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    knowtoday@know-today-pi
}

run_briefing() {
  ensure_proxy_tunnel
  cd "$PROJECT_ROOT"
  "$PROJECT_ROOT/.venv/bin/python" scripts/generate_youtube_briefing.py
}

run_and_record() {
  local today="$1" error_code
  write_state "$(read_state_value last_success)" "$today" ""
  if run_briefing; then
    write_state "$today" "$today" ""
    echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] Daily briefing completed."
    return 0
  fi

  error_code=$?
  write_state "$(read_state_value last_success)" "$today" "briefing_exit_${error_code}"
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] Daily briefing failed (exit ${error_code})."
  return "$error_code"
}

install_service() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Error: automatic service installation currently supports macOS only."
    exit 1
  fi

  local unit_dir="$HOME/Library/LaunchAgents"
  local unit_file="$unit_dir/com.coodeex.know-today-briefing.plist"
  local log_dir="$HOME/Library/Logs/know-today"
  local user_id
  user_id=$(id -u)
  mkdir -p "$unit_dir" "$log_dir"

  cat > "$unit_file" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.coodeex.know-today-briefing</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$SCRIPT_DIR/run_daily_briefing.sh</string>
    <string>--run-if-due</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_ROOT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>900</integer>
  <key>StandardOutPath</key>
  <string>$log_dir/daily-briefing.out.log</string>
  <key>StandardErrorPath</key>
  <string>$log_dir/daily-briefing.err.log</string>
</dict>
</plist>
EOF

  launchctl bootout "gui/$user_id" "$unit_file" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$user_id" "$unit_file"
  launchctl kickstart -k "gui/$user_id/com.coodeex.know-today-briefing"
  echo "Installed and started the macOS LaunchAgent."
}

if [[ "${1:-}" == "--install-service" ]]; then
  install_service
  exit 0
fi

if [[ -n "${1:-}" && "${1:-}" != "--once" && "${1:-}" != "--run-if-due" ]]; then
  echo "Usage: $0 [--once|--run-if-due|--install-service]"
  exit 1
fi

acquire_lock
trap 'rm -rf "$LOCK_DIR"' EXIT

today=$(date +%Y-%m-%d)
scheduled_epoch=$(datetime_to_epoch "${today} ${RUN_HOUR}:${RUN_MINUTE}:00")
now_epoch=$(date +%s)
last_success=$(read_state_value last_success)

if [[ "${1:-}" == "--run-if-due" ]] && (( now_epoch < scheduled_epoch )); then
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] Not due yet."
  exit 0
fi

if [[ "${1:-}" == "--run-if-due" ]] && [[ "$last_success" == "$today" ]]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] Today's briefing already succeeded."
  exit 0
fi

run_and_record "$today"
