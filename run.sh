#!/usr/bin/env bash
# Start Solar X-ray History on http://127.0.0.1:8765 and open it in the browser.
# First run creates .venv and installs requirements (uses uv if available, else python3 -m venv + pip).
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Creating .venv and installing requirements…"
  if command -v uv >/dev/null; then
    uv venv -q .venv && uv pip install -q --python .venv/bin/python -r requirements.txt || exit 1
  else
    python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
  fi
fi
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8765}
[[ -z "${NO_OPEN:-}" ]] && ( sleep 1.5; open "http://127.0.0.1:$PORT" 2>/dev/null || xdg-open "http://127.0.0.1:$PORT" 2>/dev/null ) &
exec .venv/bin/python -m uvicorn solarhist.server:app --host "$HOST" --port "$PORT"
