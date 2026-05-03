#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="grouptrade-bot.service"
SERVICE_DIR="${HOME}/.config/systemd/user"
SERVICE_PATH="${SERVICE_DIR}/${SERVICE_NAME}"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing virtualenv Python: ${PYTHON_BIN}" >&2
  echo "Create it first: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -f "${REPO_ROOT}/.env" ]]; then
  echo "Missing .env file: ${REPO_ROOT}/.env" >&2
  echo "Create it first: cp .env.example .env" >&2
  exit 1
fi

mkdir -p "${SERVICE_DIR}" "${REPO_ROOT}/logs"

cat > "${SERVICE_PATH}" <<EOF
[Unit]
Description=GroupTrade Bot Uvicorn App
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${REPO_ROOT}
Environment=PYTHONUNBUFFERED=1
ExecStart=${PYTHON_BIN} -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
Restart=always
RestartSec=10
StandardOutput=append:${REPO_ROOT}/logs/bot.out.log
StandardError=append:${REPO_ROOT}/logs/bot.err.log

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable "${SERVICE_NAME}"
systemctl --user restart "${SERVICE_NAME}"

if command -v loginctl >/dev/null 2>&1; then
  loginctl enable-linger "${USER}" >/dev/null 2>&1 || true
fi

echo "Installed and started ${SERVICE_NAME}"
echo "Status:  systemctl --user status ${SERVICE_NAME}"
echo "Logs:    tail -f ${REPO_ROOT}/logs/bot.out.log ${REPO_ROOT}/logs/bot.err.log"
echo "Stop:    systemctl --user stop ${SERVICE_NAME}"
