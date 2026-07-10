# Unplanned Restart Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the Palworld service shuts down without the bot having triggered it (via `/restart` or the RAM auto-restart), post a distinct "Server restarted unexpectedly" Discord embed to the alerts channel, with a best-effort, extensible cause explanation instead of the generic "Server shutting down" message.

**Architecture:** All changes live in the existing single-file `main.py` (per `CLAUDE.md`, no package split without asking). The existing `_auto_restart_in_progress` flag is renamed to `_bot_restart_in_progress` and is now set around *both* restart paths (`/restart` and the RAM auto-restart), so `log_tailer` can reliably tell a bot-initiated shutdown from an external one. `broadcast_embed` gains an optional `fields` parameter. A small extensible list of async "cause detector" functions is checked when a shutdown is unplanned; the first detector recognizes an `unattended-upgrades` package install immediately preceding the restart (the `needrestart` pattern from the 2026-07-10 incident).

**Tech Stack:** Python 3.14, discord.py, asyncio. No test framework in this repo.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-10-unplanned-restart-notification-design.md` — every requirement below traces back to it.
- No automated test runner exists in this repo (see `CLAUDE.md`). Verification uses `python -m py_compile main.py` for syntax, standalone `python` scratch scripts for pure/isolable logic (copied out, since `main.py` cannot be imported without a real `.env`/Discord token/Linux host), and manual trace review for the parts that need Discord/systemd/journalctl at runtime.
- `main.py` only runs on Linux, on the same host as the Palworld server — it cannot be run end-to-end in this development environment (Windows). Do not attempt to `python main.py` here.
- Unplanned-restart embed title is exactly `"Server restarted unexpectedly"` — no emoji.
- Cause text is plain language, no Linux commands/paths/package names surfaced to Discord:
  - Detected: `"A routine system update installed a security patch that caused a restart."`
  - Unknown: `"Unknown — an admin will need to check the server logs."`
- Notification is Discord-only (`ALERTS_CHANNEL_ID`) — no in-game broadcast for unplanned restarts.
- Keep everything in `main.py` — no new files, no new dependencies.

---

### Task 1: Rename the in-progress flag and cover `/restart` with it

**Files:**
- Modify: `main.py:132` (flag declaration)
- Modify: `main.py:334-360` (`auto_restart_sequence`)
- Modify: `main.py:441` (`log_tailer`'s `VERSION_RE` branch)
- Modify: `main.py:573-589` (`/restart` command)

**Interfaces:**
- Produces: module-level `_bot_restart_in_progress` (bool) — read by Task 2's `log_tailer` branch, set/cleared by both restart paths.

- [ ] **Step 1: Rename the flag at its declaration**

Replace `main.py:132`:

```python
_auto_restart_in_progress = False  # suppresses log_tailer's own "Server is online" during a sequence
```

with:

```python
_bot_restart_in_progress = False  # true while a bot-initiated restart (/restart or auto) is in flight
```

- [ ] **Step 2: Update `auto_restart_sequence` to use the renamed flag**

In `main.py`, `auto_restart_sequence` (currently lines 334-360) uses `global _auto_restart_in_progress` and sets/clears it around `restart_palworld()`. Replace:

```python
async def auto_restart_sequence(pct):
    global _auto_restart_in_progress
```

with:

```python
async def auto_restart_sequence(pct):
    global _bot_restart_in_progress
```

And replace the two lines that set/clear it:

```python
    _auto_restart_in_progress = True
    try:
        embed = await restart_palworld()
    finally:
        _auto_restart_in_progress = False
```

with:

```python
    _bot_restart_in_progress = True
    try:
        embed = await restart_palworld()
    finally:
        _bot_restart_in_progress = False
```

- [ ] **Step 3: Update `log_tailer`'s `VERSION_RE` branch to use the renamed flag**

Replace `main.py:441`:

```python
                        if not _auto_restart_in_progress:
```

with:

```python
                        if not _bot_restart_in_progress:
```

- [ ] **Step 4: Make `/restart` set the flag around its call to `restart_palworld`**

Replace the `/restart` command (`main.py:573-589`):

```python
@bot.tree.command(description="Restart the Palworld service")
@is_admin()
async def restart(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Restarting Palworld server",
        color=COLOR_SHUTDOWN,
    )
    embed.add_field(name="Status", value="Sending restart command…")
    await interaction.response.send_message(embed=embed)

    async def on_progress(status):
        embed.set_field_at(0, name="Status", value=status)
        await interaction.edit_original_response(embed=embed)

    result_embed = await restart_palworld(on_progress)
    await interaction.edit_original_response(embed=result_embed)
```

with:

```python
@bot.tree.command(description="Restart the Palworld service")
@is_admin()
async def restart(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Restarting Palworld server",
        color=COLOR_SHUTDOWN,
    )
    embed.add_field(name="Status", value="Sending restart command…")
    await interaction.response.send_message(embed=embed)

    async def on_progress(status):
        embed.set_field_at(0, name="Status", value=status)
        await interaction.edit_original_response(embed=embed)

    global _bot_restart_in_progress
    _bot_restart_in_progress = True
    try:
        result_embed = await restart_palworld(on_progress)
    finally:
        _bot_restart_in_progress = False
    await interaction.edit_original_response(embed=result_embed)
```

- [ ] **Step 5: Verify syntax**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0.

- [ ] **Step 6: Manual trace review (no test runner available)**

Re-read the four edited spots and confirm:
- No remaining references to `_auto_restart_in_progress` anywhere in `main.py` (search the file).
- `_bot_restart_in_progress` is set to `True` before `restart_palworld()` is awaited and reset to `False` in a `finally` block, in *both* `auto_restart_sequence` and the `/restart` command — so it's correctly cleared even if `restart_palworld()` raises.

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "Rename restart-in-progress flag and cover /restart with it

Previously only the RAM auto-restart set this flag, so /restart's own
service cycle looked identical to an external/unplanned one to
log_tailer (and caused a duplicate 'Server is online' post)."
```

---

### Task 2: `broadcast_embed` gains an optional `fields` parameter

**Files:**
- Modify: `main.py:113-124` (`broadcast_embed`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `async def broadcast_embed(title, description, color, dt=None, channel_id=ACTIVITY_CHANNEL_ID, fields=None) -> None`. `fields`, if given, is an iterable of `(name, value)` pairs added to the embed via `embed.add_field(name=name, value=value)`. Used by Task 4.

- [ ] **Step 1: Add the `fields` parameter**

Replace `main.py:113-124`:

```python
async def broadcast_embed(title, description, color, dt=None, channel_id=ACTIVITY_CHANNEL_ID):
    embed = discord.Embed(title=title, description=description, color=color)
    if dt:
        embed.timestamp = dt
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        log.warning("broadcast failed: channel %s not found or not a text channel", channel_id)
        return
    try:
        await channel.send(embed=embed)
    except Exception:
        log.exception("broadcast failed")
```

with:

```python
async def broadcast_embed(title, description, color, dt=None, channel_id=ACTIVITY_CHANNEL_ID, fields=None):
    embed = discord.Embed(title=title, description=description, color=color)
    if dt:
        embed.timestamp = dt
    for name, value in fields or []:
        embed.add_field(name=name, value=value)
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        log.warning("broadcast failed: channel %s not found or not a text channel", channel_id)
        return
    try:
        await channel.send(embed=embed)
    except Exception:
        log.exception("broadcast failed")
```

- [ ] **Step 2: Verify syntax**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Verify existing callers are unaffected**

Search `main.py` for `broadcast_embed(` and confirm every existing call site omits `fields` (positional/keyword args unchanged), so `fields=None` (no-op, empty loop) preserves current behavior exactly.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "Add optional fields parameter to broadcast_embed"
```

---

### Task 3: Cause-detector registry and the unattended-upgrades detector

**Files:**
- Modify: `main.py:1-9` (imports)
- Modify: `main.py:44-48` (regex constants block)
- Modify: `main.py:449` area — add new functions just above `# ---------- Discord -> game ----------` (currently `main.py:449`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `UPGRADE_LOG_RE` (module-level compiled regex), `_read_last_lines(path: str, n: int) -> list[str]`, `async def detect_unattended_upgrades(shutdown_dt: datetime) -> str | None`, `CAUSE_DETECTORS: list[Callable[[datetime], Awaitable[str | None]]]`, `async def detect_unplanned_restart_cause(shutdown_dt: datetime) -> str | None` — all used by Task 4.

- [ ] **Step 1: Add the `Callable`/`Awaitable` import**

Replace `main.py:1-9`:

```python
import os
import re
import json
import time
import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
```

with:

```python
import os
import re
import json
import time
import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo
```

- [ ] **Step 2: Add the log-line regex next to the other regex constants**

Replace `main.py:44-48`:

```python
JOIN_RE     = re.compile(r'\[LOG\]\s*(.+?) joined the server')
LEAVE_RE    = re.compile(r'\[LOG\]\s*(.+?) left the server')
TS_RE       = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)')
SHUTDOWN_RE = re.compile(r'Shutdown handler: initialize\.')
VERSION_RE  = re.compile(r'Game version is (v[\d.]+)')
```

with:

```python
JOIN_RE     = re.compile(r'\[LOG\]\s*(.+?) joined the server')
LEAVE_RE    = re.compile(r'\[LOG\]\s*(.+?) left the server')
TS_RE       = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)')
SHUTDOWN_RE = re.compile(r'Shutdown handler: initialize\.')
VERSION_RE  = re.compile(r'Game version is (v[\d.]+)')
UPGRADE_LOG_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO Packages that will be upgraded: (.+)$'
)
```

- [ ] **Step 3: Add the detector registry and the unattended-upgrades detector**

In `main.py`, directly above `# ---------- Discord -> game ----------` (currently line 449), add:

```python
# ---------- Unplanned-restart cause detection ----------
UNATTENDED_UPGRADES_LOG = "/var/log/unattended-upgrades/unattended-upgrades.log"


def _read_last_lines(path, n):
    with open(path) as f:
        return f.readlines()[-n:]


async def detect_unattended_upgrades(shutdown_dt):
    try:
        lines = await asyncio.to_thread(_read_last_lines, UNATTENDED_UPGRADES_LOG, 100)
    except OSError:
        return None

    for line in reversed(lines):
        m = UPGRADE_LOG_RE.match(line.strip())
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        delta = (shutdown_dt.astimezone(timezone.utc) - ts).total_seconds()
        if -30 <= delta <= 120:
            return "A routine system update installed a security patch that caused a restart."
        return None  # most recent entry too far from the shutdown time — no match
    return None


CAUSE_DETECTORS: list[Callable[[datetime], Awaitable[str | None]]] = [
    detect_unattended_upgrades,
]


async def detect_unplanned_restart_cause(shutdown_dt):
    for detector in CAUSE_DETECTORS:
        try:
            result = await detector(shutdown_dt)
        except Exception:
            log.exception("cause detector %s failed", detector.__name__)
            continue
        if result:
            return result
    return None
```

- [ ] **Step 4: Verify syntax**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0.

- [ ] **Step 5: Verify `detect_unattended_upgrades` window logic in isolation**

`main.py` can't be imported without a real `.env`/Discord token, so verify the time-window logic by copying it into a throwaway script that fakes the file read.

Create `C:\Users\byron\AppData\Local\Temp\claude\C--Users-byron-PycharmProjects-swee\0fc73945-bb39-496d-9730-e0ff97778c7f\scratchpad\test_detect_unattended_upgrades.py`:

```python
import asyncio
import re
from datetime import datetime, timezone

UPGRADE_LOG_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO Packages that will be upgraded: (.+)$'
)


async def detect_unattended_upgrades(shutdown_dt, lines):
    for line in reversed(lines):
        m = UPGRADE_LOG_RE.match(line.strip())
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        delta = (shutdown_dt.astimezone(timezone.utc) - ts).total_seconds()
        if -30 <= delta <= 120:
            return "A routine system update installed a security patch that caused a restart."
        return None
    return None


# Real incident: upgrade logged 06:37:51, shutdown at 06:37:53 (2s gap) -> match
lines = [
    "2026-07-10 06:37:49,218 INFO Starting unattended upgrades script\n",
    "2026-07-10 06:37:51,889 INFO Packages that will be upgraded: curl libcurl3t64-gnutls libcurl4t64\n",
    "2026-07-10 06:38:09,507 INFO All upgrades installed\n",
]
shutdown_dt = datetime(2026, 7, 10, 6, 37, 53, tzinfo=timezone.utc)
result = asyncio.run(detect_unattended_upgrades(shutdown_dt, lines))
assert result == "A routine system update installed a security patch that caused a restart.", result

# Upgrade happened, but shutdown is 10 minutes later -> no match (outside window)
shutdown_dt_far = datetime(2026, 7, 10, 6, 47, 53, tzinfo=timezone.utc)
result_far = asyncio.run(detect_unattended_upgrades(shutdown_dt_far, lines))
assert result_far is None, result_far

# No upgrade log entries at all -> no match
result_empty = asyncio.run(detect_unattended_upgrades(shutdown_dt, []))
assert result_empty is None, result_empty

# Shutdown happens 5s BEFORE the log line is written (clock skew / ordering) -> still within -30s tolerance
shutdown_dt_before = datetime(2026, 7, 10, 6, 37, 46, tzinfo=timezone.utc)
result_before = asyncio.run(detect_unattended_upgrades(shutdown_dt_before, lines))
assert result_before == "A routine system update installed a security patch that caused a restart.", result_before

print("all detect_unattended_upgrades cases passed")
```

Run: `python test_detect_unattended_upgrades.py` (from the scratchpad directory)
Expected output: `all detect_unattended_upgrades cases passed`

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "Add cause-detector registry and unattended-upgrades detector

First detector for the 2026-07-10 incident pattern: needrestart
cycling palworld.service after an unattended-upgrades package
install. More detectors can be appended to CAUSE_DETECTORS later."
```

---

### Task 4: Branch `log_tailer` on planned vs. unplanned shutdown

**Files:**
- Modify: `main.py:438-439` (the `SHUTDOWN_RE` branch inside `log_tailer`)

**Interfaces:**
- Consumes: `_bot_restart_in_progress` (Task 1), `broadcast_embed` with `fields` (Task 2), `detect_unplanned_restart_cause` (Task 3), `ALERTS_CHANNEL_ID`, `COLOR_SHUTDOWN` (existing).
- Produces: nothing new for later tasks — this is the final wiring.

- [ ] **Step 1: Replace the `SHUTDOWN_RE` branch**

Replace `main.py:438-439`:

```python
                    if SHUTDOWN_RE.search(msg):
                        await broadcast_embed("Server shutting down", None, COLOR_SHUTDOWN, dt, channel_id=ALERTS_CHANNEL_ID)
```

with:

```python
                    if SHUTDOWN_RE.search(msg):
                        if _bot_restart_in_progress:
                            await broadcast_embed("Server shutting down", None, COLOR_SHUTDOWN, dt, channel_id=ALERTS_CHANNEL_ID)
                        else:
                            cause = await detect_unplanned_restart_cause(dt)
                            await broadcast_embed(
                                "Server restarted unexpectedly",
                                None,
                                COLOR_SHUTDOWN,
                                dt,
                                channel_id=ALERTS_CHANNEL_ID,
                                fields=[("Likely cause", cause or "Unknown — an admin will need to check the server logs.")],
                            )
```

- [ ] **Step 2: Verify syntax**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Manual trace review (no test runner available)**

Re-read the full `log_tailer` function and confirm against the spec (`docs/superpowers/specs/2026-07-10-unplanned-restart-notification-design.md`):
- When `_bot_restart_in_progress` is `True` (i.e. mid-`/restart` or mid-auto-restart), the shutdown embed is unchanged from today's behavior — title `"Server shutting down"`, no extra fields.
- When `_bot_restart_in_progress` is `False`, exactly one embed is posted with title `"Server restarted unexpectedly"` and a single `"Likely cause"` field — never both the old and new message for the same shutdown event.
- The embed's cause field never contains a raw log path, command, or package name — only the two fixed strings from `detect_unattended_upgrades`/the "Unknown" fallback.
- This whole branch only runs when `RELAY_CHANNEL_ID`/other channels aren't required — confirm `ALERTS_CHANNEL_ID` is already a required env var (`main.py:33`, no `if` guard), matching how the existing shutdown message already behaves today.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "Post distinct notification for unplanned Palworld restarts

Wires the cause-detector registry into log_tailer: planned restarts
(/restart, RAM auto-restart) keep the existing plain shutdown
message; anything else gets a 'Server restarted unexpectedly' embed
with a best-effort cause."
```

---

## Post-plan manual smoke test (run on the actual Palworld host, not in this dev environment)

This cannot be automated here since `main.py` requires Linux, `journalctl`, `systemctl`, and a live Discord connection. After deploying, verify on the real host:

1. Run `/restart` and confirm the alerts channel still shows the plain "Server shutting down" embed (no "Likely cause" field) — planned path unaffected.
2. If `RAM_RESTART_THRESHOLD_PCT` is configured, trigger an auto-restart (e.g. temporarily lower the threshold) and confirm the same plain "Server shutting down" embed appears — not the unplanned-restart embed.
3. Simulate the real incident: run `sudo unattended-upgrade` (or wait for the next `apt-daily-upgrade.timer` run) on a host with a pending library upgrade that `needrestart` will act on, and confirm the alerts channel shows "Server restarted unexpectedly" with `"Likely cause: A routine system update installed a security patch that caused a restart."`.
4. Manually stop the service in a way with no matching detector (e.g. `sudo systemctl stop palworld` immediately followed by `sudo systemctl start palworld`, well outside any upgrade window) and confirm the alerts channel shows "Server restarted unexpectedly" with `"Likely cause: Unknown — an admin will need to check the server logs."`.
5. Confirm `/restart`'s own three-stage status message (Sending → Waiting → Restarted/Timed out) still works standalone and no longer double-posts "Server is online" from `log_tailer`.
