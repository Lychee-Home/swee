# Palworld Service Startup Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bot fail fast at startup, with a clear log message, if the `palworld` systemd unit is missing or passwordless sudo isn't configured — instead of silently limping along until `/restart` times out or `log_tailer` retries forever.

**Architecture:** A single synchronous function, `check_palworld_service()`, runs two `subprocess.run` checks (systemd unit LoadState, then `sudo -n true`) at the very top of `main()`, before `discord.utils.setup_logging()` or any Discord connection is attempted. On failure it logs a specific error and the process exits via `SystemExit(1)`.

**Tech Stack:** Python 3.13, stdlib `subprocess` (no new dependencies).

## Global Constraints

- No automated test suite exists in this repo (per `CLAUDE.md`) — verification is manual, run on the Linux host where the bot actually deploys (this logic depends on `systemctl`/`sudo`, which don't exist on the Windows dev machine).
- All bot logic lives in `main.py`; do not split into modules (per `CLAUDE.md`, ask before restructuring — out of scope here).
- Follow the existing logging convention: `log = logging.getLogger("swee")` already defined at module level (main.py:18); use `log.error(...)`, not `print`.

---

### Task 1: Add `check_palworld_service()` and call it from `main()`

**Files:**
- Modify: `main.py` (add `import subprocess` near the top imports; add the new function near `restart_palworld` since it's related; modify `main()`)

**Interfaces:**
- Produces: `check_palworld_service() -> bool` — returns `True` if both checks pass, `False` otherwise (and has already logged the specific reason via `log.error`).

- [ ] **Step 1: Add the `subprocess` import**

In `main.py`, the import block currently starts:

```python
import os
import re
import json
import time
import asyncio
import logging
```

Add `subprocess` alphabetically-ish alongside the others (matches existing stdlib-then-blank-line-then-third-party grouping):

```python
import os
import re
import json
import time
import asyncio
import logging
import subprocess
```

- [ ] **Step 2: Add `check_palworld_service()`**

Place this new function directly above `async def restart_palworld(...)` (main.py:375), since it's the other systemd/sudo-touching piece of code in the file:

```python
def check_palworld_service():
    load_state = subprocess.run(
        ["systemctl", "show", "-p", "LoadState", "--value", "palworld"],
        capture_output=True, text=True,
    ).stdout.strip()
    if load_state != "loaded":
        log.error("palworld.service not found (LoadState=%s) — check the unit is installed", load_state or "unknown")
        return False

    sudo_check = subprocess.run(["sudo", "-n", "true"], capture_output=True)
    if sudo_check.returncode != 0:
        log.error("passwordless sudo not configured for this user — /restart and RAM auto-restart will hang")
        return False

    return True
```

- [ ] **Step 3: Call it at the top of `main()`**

Current `main()` (main.py:451-464):

```python
async def main():
    discord.utils.setup_logging()
    async with bot:
        await bot.start(BOT_TOKEN)
        # bot.start() returns once the bot is closed (e.g. Ctrl+C) — clean up
        # the background task and REST client rather than leaving them dangling.
        stats_ticker.cancel()
        if _log_tailer_task:
            _log_tailer_task.cancel()
        await rest.client.aclose()
```

Change to:

```python
async def main():
    if not check_palworld_service():
        raise SystemExit(1)
    discord.utils.setup_logging()
    async with bot:
        await bot.start(BOT_TOKEN)
        # bot.start() returns once the bot is closed (e.g. Ctrl+C) — clean up
        # the background task and REST client rather than leaving them dangling.
        stats_ticker.cancel()
        if _log_tailer_task:
            _log_tailer_task.cancel()
        await rest.client.aclose()
```

Note: `check_palworld_service()` runs before `discord.utils.setup_logging()`, so its `log.error` calls use whatever default logging config Python has at that point (no handler configured yet → the message prints via the default "no handlers" fallback to stderr, or is dropped depending on Python version). To guarantee the error is actually visible, call `logging.basicConfig(level=logging.INFO)` first. Update the function call site once more:

```python
async def main():
    logging.basicConfig(level=logging.INFO)
    if not check_palworld_service():
        raise SystemExit(1)
    discord.utils.setup_logging()
    async with bot:
        ...
```

`discord.utils.setup_logging()` reconfigures logging for the rest of the run once we get past the check, so this early `basicConfig` only affects the brief pre-check window.

- [ ] **Step 4: Manual verification — happy path**

This requires the actual Linux host with the `palworld` service installed and sudoers configured (per `README.md`'s existing setup). Run:

```bash
python main.py
```

Expected: no "palworld.service not found" or "passwordless sudo" error lines in the startup output; the bot proceeds to log in and sync commands as before.

- [ ] **Step 5: Manual verification — missing unit**

On the same host, temporarily test with a bogus unit name to confirm the failure path works, without touching the real service. Run this one-off check directly (not by editing main.py):

```bash
systemctl show -p LoadState --value palworld-typo-test
```

Expected output: `not-found`. This confirms the `LoadState` check correctly distinguishes an installed unit from a missing one — `palworld` itself should print `loaded`:

```bash
systemctl show -p LoadState --value palworld
```

Expected output: `loaded`.

- [ ] **Step 6: Manual verification — sudo check**

Run as the same user the bot runs as:

```bash
sudo -n true; echo "exit code: $?"
```

Expected: `exit code: 0` if passwordless sudo is already configured (matching what `README.md` setup implies). If it prints a password prompt or a nonzero exit code, that's the exact condition `check_palworld_service()` is meant to catch — confirms the check would have failed loudly instead of the bot silently hanging on `/restart` later.

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "$(cat <<'EOF'
Add startup check for palworld service and passwordless sudo

restart_palworld() previously ignored the systemctl exit code, and
log_tailer() just retried forever if the unit name was wrong. Now the
bot verifies both preconditions before connecting to Discord and exits
with a clear log message if either is missing.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Post-plan note

No `docs/superpowers/` update needed beyond this plan/spec pair — `CLAUDE.md` already documents the convention generally. No `README.md` changes needed either: the check doesn't add new configuration or env vars, it just validates preconditions the README's "Running" section already assumes.
