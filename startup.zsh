conda activate trading_cards_db

#!/usr/bin/env zsh
set -euo pipefail

# run_trading_cards_db.zsh
# starts backend (app/ui) and frontend (app/ui/client) in one command
# kills both on ctrl+c and prints where to open the app

repo_root="$(cd "$(dirname "$0")" && pwd)"
ui_dir="$repo_root/app/ui"
client_dir="$ui_dir/client"

backend_pid=""
frontend_pid=""

cleanup() {
  echo ""
  echo "stopping servers..."
  if [[ -n "${frontend_pid:-}" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill "$frontend_pid" 2>/dev/null || true
  fi
  if [[ -n "${backend_pid:-}" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
  fi

  sleep 1

  if [[ -n "${frontend_pid:-}" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill -9 "$frontend_pid" 2>/dev/null || true
  fi
  if [[ -n "${backend_pid:-}" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill -9 "$backend_pid" 2>/dev/null || true
  fi
}

trap cleanup INT TERM EXIT

if [[ ! -d "$ui_dir" ]] || [[ ! -d "$client_dir" ]]; then
  echo "error: expected dirs:"
  echo "  $ui_dir"
  echo "  $client_dir"
  exit 1
fi

# if you want conda env enforced, uncomment:
# if [[ "${CONDA_DEFAULT_ENV:-}" != "trading_cards_db" ]]; then
#   echo "warning: conda env is not trading_cards_db (current: ${CONDA_DEFAULT_ENV:-none})"
# fi

echo "repo: $repo_root"
echo "backend: $ui_dir"
echo "frontend: $client_dir"
echo ""

# free up ports if something is already listening
kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "port $port in use by pid(s): $pids -> killing"
    kill $pids 2>/dev/null || true
    sleep 1
    pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      kill -9 $pids 2>/dev/null || true
    fi
  fi
}

kill_port 3001
kill_port 3000

echo "starting backend..."
cd "$ui_dir"
npm start > "$repo_root/.backend.log" 2>&1 &
backend_pid="$!"
echo "backend pid: $backend_pid (log: $repo_root/.backend.log)"

echo "starting frontend..."
cd "$client_dir"
npm start > "$repo_root/.frontend.log" 2>&1 &
frontend_pid="$!"
echo "frontend pid: $frontend_pid (log: $repo_root/.frontend.log)"
echo ""

echo "waiting for ports..."
for _ in {1..60}; do
  backend_ok="$(lsof -nP -iTCP:3001 -sTCP:LISTEN -t 2>/dev/null || true)"
  frontend_ok="$(lsof -nP -iTCP:3000 -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "$backend_ok" && -n "$frontend_ok" ]]; then
    break
  fi
  sleep 1
done

echo "ports:"
lsof -nP -iTCP:3001 -sTCP:LISTEN 2>/dev/null || true
lsof -nP -iTCP:3000 -sTCP:LISTEN 2>/dev/null || true
echo ""

echo "open:"
echo "  frontend: http://localhost:3000"
echo "  backend:  http://localhost:3001/health"
echo ""
echo "press ctrl+c to stop both servers"
echo ""

# keep script alive while children run; exit if either dies
while true; do
  if ! kill -0 "$backend_pid" 2>/dev/null; then
    echo "backend exited. tailing last 80 lines:"
    tail -80 "$repo_root/.backend.log" || true
    exit 1
  fi
  if ! kill -0 "$frontend_pid" 2>/dev/null; then
    echo "frontend exited. tailing last 80 lines:"
    tail -80 "$repo_root/.frontend.log" || true
    exit 1
  fi
  sleep 1
done