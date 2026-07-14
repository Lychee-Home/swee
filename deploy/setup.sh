#!/usr/bin/env bash
# One-time (but safe-to-rerun) setup for swee on a Linux host that already
# runs the palworld systemd service. Run from the repo root as the user the
# bot should run under, with sudo available:
#
#   ./deploy/setup.sh
#
# Re-running is a no-op except where real changes are needed: it will not
# overwrite an existing .env, will not reinstall packages that are already
# present, and will not touch sudoers/systemd files whose content already
# matches.
set -euo pipefail

SWEE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SWEE_USER="$(whoami)"
RUNNER_USER="${RUNNER_USER:-}"
PYTHON_BIN="python3.14"

cd "$SWEE_DIR"

echo "==> Checking for $PYTHON_BIN"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "==> $PYTHON_BIN not found, installing via apt"
    sudo apt-get update
    sudo apt-get install -y python3.14 python3.14-venv
fi

echo "==> Creating virtualenv"
if [ ! -d .venv ]; then
    "$PYTHON_BIN" -m venv .venv
else
    echo "    .venv already exists, skipping"
fi

echo "==> Installing dependencies"
.venv/bin/pip install -q -r requirements.txt

echo "==> Setting up .env"
if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    echo "    Created .env from .env.example — fill in your secrets before starting the bot."
else
    echo "    .env already exists, leaving it alone"
    chmod 600 .env
fi

PALWORLD_SERVICE_NAME="$(grep -E '^PALWORLD_SERVICE_NAME=' .env | cut -d= -f2- || true)"
PALWORLD_SERVICE_NAME="${PALWORLD_SERVICE_NAME:-palworld}"

echo "==> Checking ${PALWORLD_SERVICE_NAME}.service"
LOAD_STATE="$(systemctl show -p LoadState --value "$PALWORLD_SERVICE_NAME" 2>/dev/null || true)"
if [ "$LOAD_STATE" != "loaded" ]; then
    echo "    WARNING: ${PALWORLD_SERVICE_NAME}.service not found (LoadState=${LOAD_STATE:-unknown})."
    echo "    The bot's /restart command and RAM auto-restart need a systemd unit named '${PALWORLD_SERVICE_NAME}'"
    echo "    (set PALWORLD_SERVICE_NAME in .env if your unit has a different name)."
fi

echo "==> Checking passwordless sudo for 'systemctl restart ${PALWORLD_SERVICE_NAME}'"
SUDOERS_FILE="/etc/sudoers.d/swee-palworld-restart"
SUDOERS_LINE="$SWEE_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart $PALWORLD_SERVICE_NAME"
if [ "$(sudo cat "$SUDOERS_FILE" 2>/dev/null || true)" != "$SUDOERS_LINE" ]; then
    TMP_SUDOERS="$(mktemp)"
    echo "$SUDOERS_LINE" > "$TMP_SUDOERS"
    sudo visudo -cf "$TMP_SUDOERS"
    sudo install -m 440 -o root -g root "$TMP_SUDOERS" "$SUDOERS_FILE"
    rm -f "$TMP_SUDOERS"
    echo "    Installed $SUDOERS_FILE"
else
    echo "    Already configured, skipping"
fi

CI_RESTART_USER="${RUNNER_USER:-$SWEE_USER}"
echo "==> Checking passwordless sudo for 'systemctl restart swee' (as $CI_RESTART_USER)"
SWEE_SUDOERS_FILE="/etc/sudoers.d/swee-self-restart"
SWEE_SUDOERS_LINE="$CI_RESTART_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart swee"
if [ "$(sudo cat "$SWEE_SUDOERS_FILE" 2>/dev/null || true)" != "$SWEE_SUDOERS_LINE" ]; then
    TMP_SUDOERS="$(mktemp)"
    echo "$SWEE_SUDOERS_LINE" > "$TMP_SUDOERS"
    sudo visudo -cf "$TMP_SUDOERS"
    sudo install -m 440 -o root -g root "$TMP_SUDOERS" "$SWEE_SUDOERS_FILE"
    rm -f "$TMP_SUDOERS"
    echo "    Installed $SWEE_SUDOERS_FILE"
else
    echo "    Already configured, skipping"
fi

if [ -n "$RUNNER_USER" ]; then
    echo "==> Checking passwordless sudo for '$RUNNER_USER' to run ci-deploy.sh as $SWEE_USER"
    CI_DEPLOY_SUDOERS_FILE="/etc/sudoers.d/swee-ci-deploy"
    CI_DEPLOY_SUDOERS_LINE="$RUNNER_USER ALL=($SWEE_USER) NOPASSWD: $SWEE_DIR/deploy/ci-deploy.sh"
    if [ "$(sudo cat "$CI_DEPLOY_SUDOERS_FILE" 2>/dev/null || true)" != "$CI_DEPLOY_SUDOERS_LINE" ]; then
        TMP_SUDOERS="$(mktemp)"
        echo "$CI_DEPLOY_SUDOERS_LINE" > "$TMP_SUDOERS"
        sudo visudo -cf "$TMP_SUDOERS"
        sudo install -m 440 -o root -g root "$TMP_SUDOERS" "$CI_DEPLOY_SUDOERS_FILE"
        rm -f "$TMP_SUDOERS"
        echo "    Installed $CI_DEPLOY_SUDOERS_FILE"
    else
        echo "    Already configured, skipping"
    fi

    chmod +x "$SWEE_DIR/deploy/ci-deploy.sh"
else
    echo "==> RUNNER_USER not set, skipping separate-runner sudoers setup (CI is assumed to run as $SWEE_USER)"
fi

echo "==> Checking '$SWEE_USER' can read unattended-upgrades logs (adm group)"
if id -nG "$SWEE_USER" | tr ' ' '\n' | grep -qx adm; then
    echo "    Already in adm group, skipping"
else
    sudo usermod -aG adm "$SWEE_USER"
    echo "    Added $SWEE_USER to adm group — needed to read /var/log/unattended-upgrades/*"
    echo "    for the unplanned-restart cause detector; takes effect on next swee.service (re)start"
fi

echo "==> Installing systemd unit"
UNIT_DEST="/etc/systemd/system/swee.service"
RENDERED_UNIT="$(sed -e "s#__SWEE_USER__#${SWEE_USER}#g" -e "s#__SWEE_DIR__#${SWEE_DIR}#g" -e "s#__PALWORLD_SERVICE__#${PALWORLD_SERVICE_NAME}#g" deploy/swee.service)"
if [ "$(sudo cat "$UNIT_DEST" 2>/dev/null || true)" != "$RENDERED_UNIT" ]; then
    echo "$RENDERED_UNIT" | sudo tee "$UNIT_DEST" >/dev/null
    sudo systemctl daemon-reload
    echo "    Installed/updated $UNIT_DEST"

    if systemctl is-active --quiet swee.service; then
        read -r -p "    swee.service is running and its unit file changed — restart it now? [y/N] " REPLY
        if [[ "$REPLY" =~ ^[Yy]$ ]]; then
            sudo systemctl restart swee
            echo "    Restarted swee.service"
        else
            echo "    Skipped restart — run 'sudo systemctl restart swee' when ready"
        fi
    fi
else
    echo "    Already up to date, skipping"
fi

if ! systemctl is-enabled --quiet swee.service; then
    sudo systemctl enable swee.service
    echo "    Enabled swee.service"
else
    echo "    swee.service already enabled"
fi

echo "==> Done."
echo "Fill in .env (if you haven't already), then start the bot with:"
echo "    sudo systemctl start swee"
