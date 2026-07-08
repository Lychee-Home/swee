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
PYTHON_BIN="python3.13"

cd "$SWEE_DIR"

echo "==> Checking for $PYTHON_BIN"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "==> $PYTHON_BIN not found, installing via apt"
    sudo apt-get update
    sudo apt-get install -y python3.13 python3.13-venv
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

echo "==> Checking palworld.service"
LOAD_STATE="$(systemctl show -p LoadState --value palworld 2>/dev/null || true)"
if [ "$LOAD_STATE" != "loaded" ]; then
    echo "    WARNING: palworld.service not found (LoadState=${LOAD_STATE:-unknown})."
    echo "    The bot's /restart command and RAM auto-restart need a systemd unit named exactly 'palworld'."
fi

echo "==> Checking passwordless sudo for 'systemctl restart palworld'"
SUDOERS_FILE="/etc/sudoers.d/swee-palworld-restart"
SUDOERS_LINE="$SWEE_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart palworld"
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

echo "==> Installing systemd unit"
UNIT_DEST="/etc/systemd/system/swee.service"
RENDERED_UNIT="$(sed -e "s#__SWEE_USER__#${SWEE_USER}#g" -e "s#__SWEE_DIR__#${SWEE_DIR}#g" deploy/swee.service)"
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
