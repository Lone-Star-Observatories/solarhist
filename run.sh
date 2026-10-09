#!/bin/zsh
# Start Solar X-ray History on http://127.0.0.1:8765 and open it in the browser.
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  uv venv -q .venv && uv pip install -q --python .venv/bin/python -r requirements.txt
fi
PORT=${PORT:-8765}
[[ -z $NO_OPEN ]] && ( sleep 1.5; open "http://127.0.0.1:$PORT" ) &
exec .venv/bin/python -m uvicorn solarhist.server:app --host 127.0.0.1 --port $PORT
