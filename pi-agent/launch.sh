#!/usr/bin/env bash
set -euo pipefail
app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
data_dir="${SOLRDM_DATA_DIR:-$(dirname -- "$app_dir")/data}"
port="${SOLRDM_PORT:-8787}"
mkdir -p "$data_dir"
chmod 700 "$data_dir"
exec 9> "$data_dir/launcher.lock"
flock -x 9
export SOLRDM_LLAMA_SERVER="${SOLRDM_LLAMA_SERVER:-$app_dir/runtime/bin/llama-server}"
export PYTHONPATH="$app_dir:$app_dir/engine${PYTHONPATH:+:$PYTHONPATH}"
cd "$app_dir"
if ! python3 - "$port" <<'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:' + str(int(sys.argv[1])) + '/health', timeout=2) as response:
        status = json.load(response)
    if status.get('app') != 'SOLRDM Pi Agent':
        raise ValueError('Unexpected service')
except Exception:
    raise SystemExit(1)
PY
then
  nohup python3 -m solrdm_pi --data-dir "$data_dir" --port "$port" >> "$data_dir/server.log" 2>&1 </dev/null 9>&- &
  server_pid=$!
  printf '%s\n' "$server_pid" > "$data_dir/server.pid"
  python3 - "$port" "$server_pid" <<'PY'
import json, os, sys, time, urllib.request
for attempt in range(60):
    try:
        os.kill(int(sys.argv[2]), 0)
        with urllib.request.urlopen('http://127.0.0.1:' + str(int(sys.argv[1])) + '/health', timeout=1) as response:
            status = json.load(response)
        if status.get('app') == 'SOLRDM Pi Agent':
            break
    except Exception:
        pass
    time.sleep(0.25)
else:
    raise SystemExit('SOLRDM did not start. See the server.log file in its data directory.')
PY
fi
flock -u 9
exec 9>&-
if [[ "${SOLRDM_NO_BROWSER:-0}" != 1 ]]; then
  if command -v xdg-open >/dev/null; then
    xdg-open "http://127.0.0.1:$port/" >/dev/null 2>&1 &
  else
    printf 'Open http://127.0.0.1:%s/ in a browser on this Pi.\n' "$port"
  fi
fi
