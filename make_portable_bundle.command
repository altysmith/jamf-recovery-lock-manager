#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -d "$SCRIPT_DIR/.venv" ]]; then
  /usr/bin/python3 -m venv "$SCRIPT_DIR/.venv"
fi

VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

"$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" pyinstaller

rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/dist"

pyinstaller \
  --noconfirm \
  --clean \
  --name JamfRecoveryLockManager \
  --add-data "$SCRIPT_DIR/templates:templates" \
  --add-data "$SCRIPT_DIR/static:static" \
  "$SCRIPT_DIR/app.py" >/dev/null

echo
echo "Portable bundle created:"
echo "$SCRIPT_DIR/dist/JamfRecoveryLockManager"
echo
echo "Copy that folder to another Mac if you need a backup, along with your .env file if you want local credentials there."
