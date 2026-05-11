#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -d "$SCRIPT_DIR/.venv" ]]; then
  /usr/bin/python3 -m venv "$SCRIPT_DIR/.venv"
fi

source "$SCRIPT_DIR/.venv/bin/activate"

python -m pip install --upgrade pip >/dev/null
python -m pip install -r "$SCRIPT_DIR/requirements.txt" >/dev/null

if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

: "${JAMF_URL:?Set JAMF_URL in your environment or .env file}"
: "${CLIENT_ID:?Set CLIENT_ID in your environment or .env file}"
: "${CLIENT_SECRET:?Set CLIENT_SECRET in your environment or .env file}"

PORT="${PORT:-5001}"

echo
echo "Jamf Recovery Lock Manager"
echo "Open http://127.0.0.1:${PORT} in your browser"
echo

python "$SCRIPT_DIR/app.py"
