# Configurable Palworld service name — design

## Problem

The bot assumes the Palworld dedicated server is managed by a systemd unit named exactly
`palworld`. That name is hardcoded in six places:

- `main.py`: `log_tailer()` (`journalctl -u palworld`), `check_palworld_service()` (`systemctl show`
  and the sudo check), `restart_palworld()` (`systemctl restart`), and two log/error message
  strings that mention `palworld.service` / `journalctl -u palworld`.
- `deploy/setup.sh`: the `LoadState` check and the generated `NOPASSWD` sudoers rule.
- `deploy/swee.service`: `After=network-online.target palworld.service`.

A new host is being set up to run multiple Palworld servers side by side, each under its own
systemd unit (e.g. `palworld-palchuds`). The bot needs to target whichever unit it's configured
for instead of assuming `palworld`.

## Scope

- Add an optional `PALWORLD_SERVICE_NAME` env var, defaulting to `palworld` so existing
  deployments (whose unit actually is named `palworld`) need no `.env` change.
- Replace all six hardcoded occurrences with this configured value.
- `deploy/setup.sh` reads the value out of `.env` (after the existing "set up `.env`" step, so the
  file is guaranteed to exist) and uses it for the service check, the sudoers rule, and a new
  template substitution into `deploy/swee.service`.

Out of scope: running multiple swee instances against multiple Palworld servers on the same host,
per-server Discord channel routing, or anything about `PALWORLD_SETTINGS_INI_PATH` — that's
already a per-host path set directly in `.env` and needs no code change.

## Components

### 1. `main.py` — new config constant

```python
PALWORLD_SERVICE_NAME = os.environ.get("PALWORLD_SERVICE_NAME", "palworld")
```

Added next to the other env-derived constants (near `PALWORLD_SETTINGS_INI_PATH`, ~line 37).

### 2. `main.py` — use the constant everywhere the unit name appears

- `log_tailer()`: `"journalctl", "-u", PALWORLD_SERVICE_NAME, "-f", ...`
- `check_palworld_service()`:
  - `["systemctl", "show", "-p", "LoadState", "--value", PALWORLD_SERVICE_NAME]`
  - error message: `f"{PALWORLD_SERVICE_NAME}.service not found (LoadState=%s) — check the unit is installed"`
  - `["sudo", "-n", "-l", "systemctl", "restart", PALWORLD_SERVICE_NAME]`
  - error message: `f"passwordless sudo for 'systemctl restart {PALWORLD_SERVICE_NAME}' not configured..."`
- `restart_palworld()`:
  - `asyncio.create_subprocess_exec("sudo", "systemctl", "restart", PALWORLD_SERVICE_NAME)`
  - timeout message: `f"No response after {timeout}s — check \`journalctl -u {PALWORLD_SERVICE_NAME}\`"`

No behavior change for existing deployments, since the default is `"palworld"`.

### 3. `.env.example` — document the new var

Add under the existing "Palworld settings change alert" section (or its own small section):

```
# --- Palworld service ---
# Name of the systemd unit managing the Palworld dedicated server on this host.
# Defaults to "palworld" if unset — only set this if your unit is named differently
# (e.g. when running multiple Palworld servers on one host).
# PALWORLD_SERVICE_NAME=palworld
```

Left commented out (matching the style of other optional vars like `RAM_RESTART_THRESHOLD_PCT`)
so the default applies unless explicitly overridden.

### 4. `deploy/setup.sh` — read the value and use it

After the existing `.env` setup block (so `.env` is guaranteed to exist), add:

```bash
PALWORLD_SERVICE_NAME="$(grep -E '^PALWORLD_SERVICE_NAME=' .env | cut -d= -f2- || true)"
PALWORLD_SERVICE_NAME="${PALWORLD_SERVICE_NAME:-palworld}"
```

Then replace the three hardcoded `palworld` occurrences:

- Service check: `systemctl show -p LoadState --value "$PALWORLD_SERVICE_NAME"`, with the warning
  message interpolating `$PALWORLD_SERVICE_NAME` instead of the literal string.
- Sudoers rule: `SUDOERS_LINE="$SWEE_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart $PALWORLD_SERVICE_NAME"`.
  The sudoers filename (`/etc/sudoers.d/swee-palworld-restart`) stays as-is — it's an
  implementation detail, not user-facing, and doesn't need to vary per service name.
- Unit template rendering: add a third `sed` substitution alongside the existing
  `__SWEE_USER__`/`__SWEE_DIR__` ones:
  ```bash
  RENDERED_UNIT="$(sed -e "s#__SWEE_USER__#${SWEE_USER}#g" \
                       -e "s#__SWEE_DIR__#${SWEE_DIR}#g" \
                       -e "s#__PALWORLD_SERVICE__#${PALWORLD_SERVICE_NAME}#g" \
                       deploy/swee.service)"
  ```

Re-running `setup.sh` after changing `PALWORLD_SERVICE_NAME` in `.env` picks up the new value on
the next run (the script already re-renders and only skips when content matches, so a changed
sudoers rule or unit file is detected and reinstalled automatically).

### 5. `deploy/swee.service` — templated `After=`

```
After=network-online.target __PALWORLD_SERVICE__.service
```

Rendered by `setup.sh` per Component 4.

### 6. `README.md` — update the unit-name requirement

Replace the line asserting the unit "must be named exactly `palworld`" with a description of
`PALWORLD_SERVICE_NAME`, defaulting to `palworld`, set in `.env`.

## Error handling

- If `.env` doesn't yet contain `PALWORLD_SERVICE_NAME` (existing deployments, or a fresh `.env`
  copied from `.env.example` with the var left commented out), `setup.sh`'s `grep` finds nothing,
  the variable is empty, and the `${PALWORLD_SERVICE_NAME:-palworld}` fallback applies — matching
  `main.py`'s own default. No behavior change for anyone who doesn't set the var.
- No new failure modes in `main.py`: the value is read once at import time via `os.environ.get`,
  same pattern as every other optional env var already in the file.

## Non-goals / risks accepted

- This does not support one swee instance managing multiple Palworld servers — one bot process
  still targets exactly one systemd unit, configured via one `PALWORLD_SERVICE_NAME`. Running
  several Palworld servers on one host means running several independent swee checkouts, each with
  its own `.env` (and its own Discord bot token/channels), which is out of scope here.
- The sudoers rule filename stays `/etc/sudoers.d/swee-palworld-restart` regardless of the
  configured service name. If someone runs two swee instances on the same host as the same OS
  user, the second `setup.sh` run would overwrite the first's sudoers rule with a different
  service name. Accepted: each swee instance is expected to run as its own dedicated OS user (as
  the existing single-service design already assumes for the `swee` self-restart sudoers rule).
