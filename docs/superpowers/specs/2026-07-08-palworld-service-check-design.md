# Startup check for palworld service configuration — design

## Problem

The bot assumes the `palworld` systemd unit exists and that it can run
`sudo systemctl restart palworld` without a password prompt. Neither is verified anywhere:

- `restart_palworld()` (main.py:375-377) runs `sudo systemctl restart palworld` and ignores
  the subprocess's exit code. If the unit doesn't exist or sudo isn't configured, the command
  silently "succeeds," and the bot just polls the REST API for 120s before reporting a vague
  "Restart timed out" with no indication of the real cause.
- `log_tailer()` (main.py:267-313) runs `journalctl -u palworld -f`. If the unit name is wrong,
  the stream ends almost immediately; the surrounding retry loop just logs "stream ended,
  restarting in 5s" forever, every 5 seconds, with no clear signal that the unit is misconfigured.

Both failure modes are silent and only surface indirectly, well after the bot claims to be running.
We want the bot to fail fast and loudly at startup if these preconditions aren't met, rather than
running in a half-broken state.

## Scope

Two checks, run once, synchronously, before the bot connects to Discord:

1. **Unit exists** — the `palworld` systemd unit is installed (`LoadState == loaded`).
2. **Passwordless sudo works** — the user running the bot can run `sudo` non-interactively
   (`sudo -n true` succeeds).

If either check fails, log a clear error explaining which precondition failed and exit the
process immediately (`SystemExit(1)`) — no Discord connection is attempted.

Out of scope (explicitly excluded):
- Periodic re-checking after startup (if the unit or sudoers config changes while the bot is
  already running, it won't notice until the next restart).
- Verifying `journalctl -u palworld` read access.
- Verifying REST API reachability (`REST_HOST`/`REST_PORT`/credentials) — separate concern,
  already exercised naturally by the first `/status` or stats tick.
- Posting the failure to Discord — the bot hasn't connected yet at this point, so log-only.

## Implementation

```python
import subprocess

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

Called at the top of `main()`, before any Discord setup:

```python
async def main():
    if not check_palworld_service():
        raise SystemExit(1)
    discord.utils.setup_logging()
    async with bot:
        ...
```

Plain `subprocess.run` (blocking) is used rather than `asyncio.create_subprocess_exec` —
this runs once before the event loop's async work begins, so there's no need for the
non-blocking subprocess machinery used elsewhere in the file (`log_tailer`,
`restart_palworld`).

## Error handling

Both checks capture output/exit code rather than raising — `subprocess.run` doesn't raise by
default on nonzero exit, so no try/except is needed. Each failure path logs a specific,
actionable message (unit missing vs. sudo misconfigured) rather than a generic error, so an
admin reading the startup log immediately knows which of the two preconditions to fix.

## Non-goals / risks accepted

- `sudo -n true` verifies passwordless sudo *in general*, not specifically for
  `systemctl restart palworld`. If sudoers restricts NOPASSWD to a narrower command list that
  happens to exclude `true` (or, conversely, allows `true` but not the actual restart command),
  this check can give a false negative or false positive. Tightening it to test the exact
  restart command would mean risking an actual `--dry-run` restart, which isn't reliably
  supported across older systemd versions — not worth the complexity for this check.
- No re-check after startup — a unit removed or sudoers file changed while the bot is already
  running won't be caught until the next process restart.
- Does not check `journalctl` read access or REST API reachability — both are separate
  concerns already surfaced (if misconfigured) through existing code paths shortly after startup.
