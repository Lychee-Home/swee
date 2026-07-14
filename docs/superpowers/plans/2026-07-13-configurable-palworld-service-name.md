# Configurable Palworld Service Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the systemd unit name the bot manages/tails configurable via `PALWORLD_SERVICE_NAME` (defaulting to `palworld`), so `swee` works on hosts where the Palworld unit isn't literally named `palworld` (e.g. `palworld-palchuds` on a multi-server host).

**Architecture:** One new env-derived constant in `main.py` replaces six hardcoded `"palworld"` literals across `main.py`, `deploy/setup.sh`, and `deploy/swee.service`. `deploy/setup.sh` reads the value from `.env` (falling back to `palworld`) and threads it into the sudoers rule and the `swee.service` template render, alongside the existing `__SWEE_USER__`/`__SWEE_DIR__` substitutions.

**Tech Stack:** Python 3.14 (stdlib `os.environ` — no new dependency), bash (`deploy/setup.sh`), systemd unit file templating (`sed`).

## Global Constraints

- Default to `palworld` when `PALWORLD_SERVICE_NAME` is unset, so existing deployments need no `.env` change.
- No automated test runner exists in this repo (per `CLAUDE.md`) — verification steps below use `python -m py_compile`, `bash -n`, and manual grep/diff checks instead of a test suite.
- Never push to `main` directly — all commits in this plan go to the existing branch `configurable-palworld-service-name`.

---

### Task 1: `main.py` — add `PALWORLD_SERVICE_NAME` constant and use it everywhere

**Files:**
- Modify: `main.py:37` (add constant), `main.py:647` (`log_tailer`), `main.py:849-868` (`check_palworld_service`), `main.py:871-899` (`restart_palworld`)

**Interfaces:**
- Produces: module-level constant `PALWORLD_SERVICE_NAME: str`, used directly by name in the functions below (no parameters threaded through — matches how `PALWORLD_SETTINGS_INI_PATH` is already used as a bare module global).

- [ ] **Step 1: Add the constant**

In `main.py`, right after line 37 (`PALWORLD_SETTINGS_INI_PATH = os.environ["PALWORLD_SETTINGS_INI_PATH"]`), add:

```python
PALWORLD_SERVICE_NAME = os.environ.get("PALWORLD_SERVICE_NAME", "palworld")
```

- [ ] **Step 2: Update `log_tailer()`**

Current (`main.py:647`):
```python
                "journalctl", "-u", "palworld", "-f", "-n", "0", "-o", "json", "--no-pager",
```

Replace with:
```python
                "journalctl", "-u", PALWORLD_SERVICE_NAME, "-f", "-n", "0", "-o", "json", "--no-pager",
```

- [ ] **Step 3: Update `check_palworld_service()`**

Current (`main.py:849-868`):
```python
def check_palworld_service():
    load_state = subprocess.run(
        ["systemctl", "show", "-p", "LoadState", "--value", "palworld"],
        capture_output=True, text=True,
    ).stdout.strip()
    if load_state != "loaded":
        log.error("palworld.service not found (LoadState=%s) — check the unit is installed", load_state or "unknown")
        return False

    sudo_check = subprocess.run(
        ["sudo", "-n", "-l", "systemctl", "restart", "palworld"], capture_output=True,
    )
    if sudo_check.returncode != 0:
        log.error(
            "passwordless sudo for 'systemctl restart palworld' not configured for this user "
            "— /restart and RAM auto-restart will hang"
        )
        return False

    return True
```

Replace with:
```python
def check_palworld_service():
    load_state = subprocess.run(
        ["systemctl", "show", "-p", "LoadState", "--value", PALWORLD_SERVICE_NAME],
        capture_output=True, text=True,
    ).stdout.strip()
    if load_state != "loaded":
        log.error("%s.service not found (LoadState=%s) — check the unit is installed", PALWORLD_SERVICE_NAME, load_state or "unknown")
        return False

    sudo_check = subprocess.run(
        ["sudo", "-n", "-l", "systemctl", "restart", PALWORLD_SERVICE_NAME], capture_output=True,
    )
    if sudo_check.returncode != 0:
        log.error(
            "passwordless sudo for 'systemctl restart %s' not configured for this user "
            "— /restart and RAM auto-restart will hang", PALWORLD_SERVICE_NAME
        )
        return False

    return True
```

- [ ] **Step 4: Update `restart_palworld()`**

Current (`main.py:871-872`):
```python
async def restart_palworld(on_progress=None):
    proc = await asyncio.create_subprocess_exec("sudo", "systemctl", "restart", "palworld")
```

Replace with:
```python
async def restart_palworld(on_progress=None):
    proc = await asyncio.create_subprocess_exec("sudo", "systemctl", "restart", PALWORLD_SERVICE_NAME)
```

Current (`main.py:896-898`):
```python
        embed.add_field(
            name="Status",
            value=f"No response after {timeout}s — check `journalctl -u palworld`",
        )
```

Replace with:
```python
        embed.add_field(
            name="Status",
            value=f"No response after {timeout}s — check `journalctl -u {PALWORLD_SERVICE_NAME}`",
        )
```

- [ ] **Step 5: Verify no hardcoded literal remains and the file still compiles**

Run: `cd C:/Users/byron/PycharmProjects/swee && grep -n '"palworld"' main.py`
Expected: no output (empty) — every unit-name literal has been replaced. (This grep will still match unrelated things like `"palworld"` inside dict-based settings keys if any exist — confirm any hit is unrelated to the systemd unit name before treating it as a problem.)

Run: `cd C:/Users/byron/PycharmProjects/swee && python -m py_compile main.py`
Expected: exits 0, no output.

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat: make Palworld systemd unit name configurable via PALWORLD_SERVICE_NAME"
```

---

### Task 2: `.env.example` — document `PALWORLD_SERVICE_NAME`

**Files:**
- Modify: `.env.example` (after line 43, the `PALWORLD_SETTINGS_INI_PATH` line)

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: nothing consumed by later tasks — purely descriptive, but confirms the env var name matches Task 1's `os.environ.get("PALWORLD_SERVICE_NAME", ...)` call exactly.

- [ ] **Step 1: Add the new section**

Append to `.env.example` (after the existing `PALWORLD_SETTINGS_INI_PATH=` line):

```
# --- Palworld service ---
# Name of the systemd unit managing the Palworld dedicated server on this host.
# Defaults to "palworld" if unset — only set this if your unit is named differently
# (e.g. when running multiple Palworld servers on one host).
# PALWORLD_SERVICE_NAME=palworld
```

- [ ] **Step 2: Verify the var name matches `main.py` exactly**

Run: `cd C:/Users/byron/PycharmProjects/swee && grep -o 'PALWORLD_SERVICE_NAME' .env.example main.py`
Expected: both files list `PALWORLD_SERVICE_NAME` — confirms no typo mismatch between the documented name and the one `os.environ.get` reads.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: document PALWORLD_SERVICE_NAME in .env.example"
```

---

### Task 3: `deploy/swee.service` — templated `After=`

**Files:**
- Modify: `deploy/swee.service:6`

**Interfaces:**
- Produces: placeholder token `__PALWORLD_SERVICE__` in the unit file, consumed by Task 4's `sed` substitution in `deploy/setup.sh`.

- [ ] **Step 1: Replace the hardcoded unit name in `After=`**

Current (`deploy/swee.service:6`):
```
After=network-online.target palworld.service
```

Replace with:
```
After=network-online.target __PALWORLD_SERVICE__.service
```

Also update the header comment (`deploy/swee.service:2-3`) which currently says setup.sh substitutes `__SWEE_USER__` and `__SWEE_DIR__` — add the new placeholder to that list:

Current:
```
# Installed to /etc/systemd/system/swee.service by deploy/setup.sh, which
# substitutes __SWEE_USER__ and __SWEE_DIR__ for the values it was run with.
```

Replace with:
```
# Installed to /etc/systemd/system/swee.service by deploy/setup.sh, which
# substitutes __SWEE_USER__, __SWEE_DIR__, and __PALWORLD_SERVICE__ for the
# values it was run with.
```

- [ ] **Step 2: Verify the placeholder is present**

Run: `cd C:/Users/byron/PycharmProjects/swee && grep -n '__PALWORLD_SERVICE__' deploy/swee.service`
Expected: two matches — one in the header comment, one in `After=`.

- [ ] **Step 3: Commit**

```bash
git add deploy/swee.service
git commit -m "feat: template Palworld unit name into swee.service After="
```

---

### Task 4: `deploy/setup.sh` — read `PALWORLD_SERVICE_NAME` and use it in the service check, sudoers rule, and unit render

**Files:**
- Modify: `deploy/setup.sh:47-66` (service check + sudoers rule), `deploy/setup.sh:84` (unit render)

**Interfaces:**
- Consumes: `.env` file (guaranteed to exist by this point in the script — the earlier "Setting up .env" block at `deploy/setup.sh:37-45` runs first) and Task 3's `__PALWORLD_SERVICE__` placeholder in `deploy/swee.service`.
- Produces: shell variable `PALWORLD_SERVICE_NAME`, used in the three spots below.

- [ ] **Step 1: Read the value from `.env` right before the service check**

Current (`deploy/setup.sh:46-48`):
```bash

echo "==> Checking palworld.service"
LOAD_STATE="$(systemctl show -p LoadState --value palworld 2>/dev/null || true)"
```

Replace with:
```bash

PALWORLD_SERVICE_NAME="$(grep -E '^PALWORLD_SERVICE_NAME=' .env | cut -d= -f2- || true)"
PALWORLD_SERVICE_NAME="${PALWORLD_SERVICE_NAME:-palworld}"

echo "==> Checking ${PALWORLD_SERVICE_NAME}.service"
LOAD_STATE="$(systemctl show -p LoadState --value "$PALWORLD_SERVICE_NAME" 2>/dev/null || true)"
```

- [ ] **Step 2: Update the warning message**

Current (`deploy/setup.sh:49-52`):
```bash
if [ "$LOAD_STATE" != "loaded" ]; then
    echo "    WARNING: palworld.service not found (LoadState=${LOAD_STATE:-unknown})."
    echo "    The bot's /restart command and RAM auto-restart need a systemd unit named exactly 'palworld'."
fi
```

Replace with:
```bash
if [ "$LOAD_STATE" != "loaded" ]; then
    echo "    WARNING: ${PALWORLD_SERVICE_NAME}.service not found (LoadState=${LOAD_STATE:-unknown})."
    echo "    The bot's /restart command and RAM auto-restart need a systemd unit named '${PALWORLD_SERVICE_NAME}'"
    echo "    (set PALWORLD_SERVICE_NAME in .env if your unit has a different name)."
fi
```

- [ ] **Step 3: Update the sudoers rule for the Palworld restart**

Current (`deploy/setup.sh:54-56`):
```bash
echo "==> Checking passwordless sudo for 'systemctl restart palworld'"
SUDOERS_FILE="/etc/sudoers.d/swee-palworld-restart"
SUDOERS_LINE="$SWEE_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart palworld"
```

Replace with:
```bash
echo "==> Checking passwordless sudo for 'systemctl restart ${PALWORLD_SERVICE_NAME}'"
SUDOERS_FILE="/etc/sudoers.d/swee-palworld-restart"
SUDOERS_LINE="$SWEE_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart $PALWORLD_SERVICE_NAME"
```

(The remaining lines in that block — writing to `$TMP_SUDOERS`, `visudo -cf`, `install`, the "Installed"/"Already configured" echoes — are unchanged; they already reference `$SUDOERS_LINE`/`$SUDOERS_FILE` generically.)

- [ ] **Step 4: Add the third `sed` substitution to the unit render**

Current (`deploy/setup.sh:84`):
```bash
RENDERED_UNIT="$(sed -e "s#__SWEE_USER__#${SWEE_USER}#g" -e "s#__SWEE_DIR__#${SWEE_DIR}#g" deploy/swee.service)"
```

Replace with:
```bash
RENDERED_UNIT="$(sed -e "s#__SWEE_USER__#${SWEE_USER}#g" -e "s#__SWEE_DIR__#${SWEE_DIR}#g" -e "s#__PALWORLD_SERVICE__#${PALWORLD_SERVICE_NAME}#g" deploy/swee.service)"
```

- [ ] **Step 5: Verify the script's syntax and that no hardcoded literal remains**

Run: `cd C:/Users/byron/PycharmProjects/swee && bash -n deploy/setup.sh`
Expected: exits 0, no output (bash syntax check only — does not execute the script, since it requires `sudo`/systemd and shouldn't be run outside the target host).

Run: `cd C:/Users/byron/PycharmProjects/swee && grep -n 'restart palworld\|-value palworld\|palworld\.service' deploy/setup.sh`
Expected: no output — confirms every literal `palworld` unit reference in the script is now `$PALWORLD_SERVICE_NAME`/`${PALWORLD_SERVICE_NAME}`.

- [ ] **Step 6: Commit**

```bash
git add deploy/setup.sh
git commit -m "feat: read PALWORLD_SERVICE_NAME in setup.sh for service check, sudoers, and unit render"
```

---

### Task 5: `README.md` — update the unit-name requirement

**Files:**
- Modify: `README.md:11` (journalctl mention), `README.md:25` (RAM auto-restart mention), `README.md:72-75` (unit-name requirement paragraph), `README.md:81-82` (deploy section mention)

**Interfaces:**
- Consumes: nothing — documentation only, describing behavior already implemented in Tasks 1–4.

- [ ] **Step 1: Update the `journalctl` bullet**

Current (`README.md:11`):
```
- **`journalctl -u palworld -f`** — tailed for chat/join/leave/shutdown/version log lines. Join/leave
```

Replace with:
```
- **`journalctl -u $PALWORLD_SERVICE_NAME -f`** (`palworld` by default) — tailed for chat/join/leave/shutdown/version log lines. Join/leave
```

- [ ] **Step 2: Update the RAM auto-restart bullet**

Current (`README.md:24-25`):
```
- **RAM auto-restart** (optional) — if `RAM_RESTART_THRESHOLD_PCT` is set, the stats ticker
  restarts the `palworld` service whenever host RAM usage crosses that percentage. Players get
```

Replace with:
```
- **RAM auto-restart** (optional) — if `RAM_RESTART_THRESHOLD_PCT` is set, the stats ticker
  restarts the Palworld service (`PALWORLD_SERVICE_NAME`, `palworld` by default) whenever host RAM usage crosses that percentage. Players get
```

- [ ] **Step 3: Replace the unit-name requirement paragraph**

Current (`README.md:72-75`):
```
The systemd unit managing the Palworld service must be named exactly `palworld`. Additionally, the
user running the bot must have passwordless `sudo` configured for the `systemctl restart palworld`
command (e.g. via a `NOPASSWD` sudoers entry) — otherwise the bot exits immediately at startup with
a clear error in the log.
```

Replace with:
```
The systemd unit managing the Palworld service defaults to `palworld` — set `PALWORLD_SERVICE_NAME`
in `.env` if yours is named differently (e.g. when running multiple Palworld servers on one host).
Additionally, the user running the bot must have passwordless `sudo` configured for the
`systemctl restart <PALWORLD_SERVICE_NAME>` command (e.g. via a `NOPASSWD` sudoers entry) —
otherwise the bot exits immediately at startup with a clear error in the log.
```

- [ ] **Step 4: Update the deploy section mention**

Current (`README.md:79-83`):
```
For a Linux host you set up once and leave running, `deploy/setup.sh` automates the steps above
plus the systemd wiring: it creates the venv, installs dependencies, copies `.env.example` to
`.env` (without overwriting an existing one), checks that `palworld.service` exists, installs a
passwordless-sudo rule scoped to `systemctl restart palworld`, and installs/enables a
`swee.service` unit (rendered from `deploy/swee.service`). It's safe to re-run — it skips any step
```

Replace with:
```
For a Linux host you set up once and leave running, `deploy/setup.sh` automates the steps above
plus the systemd wiring: it creates the venv, installs dependencies, copies `.env.example` to
`.env` (without overwriting an existing one), checks that the configured Palworld service (from
`PALWORLD_SERVICE_NAME` in `.env`, `palworld` by default) exists, installs a passwordless-sudo rule
scoped to restarting it, and installs/enables a `swee.service` unit (rendered from
`deploy/swee.service`). It's safe to re-run — it skips any step
```

- [ ] **Step 5: Verify the stale claim is gone**

Run: `cd C:/Users/byron/PycharmProjects/swee && grep -n 'named exactly .palworld.' README.md`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: document PALWORLD_SERVICE_NAME in README"
```

---

### Task 6: End-to-end review

**Files:** none (verification only)

**Interfaces:** none.

- [ ] **Step 1: Confirm no stray hardcoded unit-name literal remains anywhere touched by this plan**

Run: `cd C:/Users/byron/PycharmProjects/swee && grep -rn '"palworld"\|'"'"'palworld'"'"'\|restart palworld\|-u palworld\| palworld\.service' main.py deploy/setup.sh deploy/swee.service README.md`
Expected: no output. (If anything matches, it's a spot this plan missed — fix it before moving on.)

- [ ] **Step 2: Sanity-check the bot still imports cleanly**

Run: `cd C:/Users/byron/PycharmProjects/swee && python -m py_compile main.py && echo OK`
Expected: `OK`

- [ ] **Step 3: Push the branch and open the PR**

```bash
git push -u origin configurable-palworld-service-name
gh pr create --title "feat: make Palworld systemd unit name configurable" --body "$(cat <<'EOF'
## Summary
- Adds PALWORLD_SERVICE_NAME (default "palworld") so swee works against a non-default
  Palworld systemd unit name, needed for the new multi-server host.
- Threads the value through main.py, deploy/setup.sh, and deploy/swee.service.

## Test plan
- [ ] python -m py_compile main.py
- [ ] bash -n deploy/setup.sh
- [ ] Manual review: grep confirms no hardcoded "palworld" unit-name literal remains
- [ ] Run deploy/setup.sh on the new host with PALWORLD_SERVICE_NAME=palworld-palchuds in .env and confirm the sudoers rule and swee.service render with the right name

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

(This step needs your go-ahead before running — pushing and opening the PR are visible, hard-to-fully-reverse actions.)
