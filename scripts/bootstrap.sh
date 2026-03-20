#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/opt/webhooker"
VENV_PATH="$PROJECT_ROOT/.venv"
CONFIG_PATH="/etc/webhooker/projects"
SYSTEMD_PATH="/etc/systemd/system"

python3.14 -m venv "$VENV_PATH"
"$VENV_PATH/bin/pip" install --upgrade pip
"$VENV_PATH/bin/pip" install "$PROJECT_ROOT"

install -d -m 0755 "$CONFIG_PATH"
install -m 0644 "$PROJECT_ROOT/config/example.project.yaml" "$CONFIG_PATH/example.review.yaml"
install -m 0644 "$PROJECT_ROOT/config/example.production.yaml" "$CONFIG_PATH/example.production.yaml"
install -m 0644 "$PROJECT_ROOT/systemd/webhooker-api.service" "$SYSTEMD_PATH/webhooker-api.service"
install -m 0644 "$PROJECT_ROOT/systemd/webhooker-worker.service" "$SYSTEMD_PATH/webhooker-worker.service"
install -m 0644 "$PROJECT_ROOT/systemd/webhooker-worker.timer" "$SYSTEMD_PATH/webhooker-worker.timer"

echo "Bootstrap complete. Review environment variables before enabling systemd units."
