#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="grouptrade-bot.service"
SERVICE_PATH="${HOME}/.config/systemd/user/${SERVICE_NAME}"

systemctl --user stop "${SERVICE_NAME}" >/dev/null 2>&1 || true
systemctl --user disable "${SERVICE_NAME}" >/dev/null 2>&1 || true
rm -f "${SERVICE_PATH}"
systemctl --user daemon-reload

echo "Removed ${SERVICE_NAME}"
