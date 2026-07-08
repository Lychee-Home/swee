# RAM-Triggered Auto-Restart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Have the bot automatically warn players and restart the `palworld` systemd service when host RAM usage crosses a configurable threshold, reusing the existing `/restart` restart-and-wait-for-online logic.

**Architecture:** All changes live in the existing single-file `main.py` (per `CLAUDE.md`, no package split without asking). `read_ram_stats()` is split out of `get_ram_usage()` so the ticker can get the raw percentage. A pure `should_auto_restart()` helper decides whether to fire, given the threshold/cooldown as explicit arguments so it's testable without importing the rest of the module. The `/restart` command's body is extracted into `restart_palworld()`, reused by a new `auto_restart_sequence()` spawned from the existing 1-minute `stats_ticker` loop.

**Tech Stack:** Python 3.13, discord.py, httpx, asyncio. No test framework in this repo.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-07-ram-auto-restart-design.md` — every requirement below traces back to it.
- No automated test runner exists in this repo (see `CLAUDE.md`). Verification in this plan uses `python -m py_compile main.py` for syntax, standalone `python -c` snippets for pure logic (copy-pasted, since `main.py` cannot be imported without a real `.env`/Discord token/Linux host), and a manual smoke-test checklist for the parts that need Discord/systemd/`/proc` at runtime.
- `main.py` only runs on Linux, on the same host as the Palworld server — it cannot be run end-to-end in this development environment (Windows). Do not attempt to `python main.py` here.
- All new env vars are optional; if `RAM_RESTART_THRESHOLD_PCT` is unset, none of the new code paths should execute.
- Keep everything in `main.py` — no new files, no new dependencies.

---

### Task 1: Config vars, `read_ram_stats()` split, and the trigger-decision helper

**Files:**
- Modify: `main.py:20-29` (env var block)
- Modify: `main.py:109-122` (`get_ram_usage`)
- Modify: `.env.example`

**Interfaces:**
- Produces: `RAM_RESTART_THRESHOLD_PCT` (float or `None`), `RAM_RESTART_COOLDOWN_MIN` (float), `RAM_RESTART_WARNING_SEC` (float) — module-level config used by Task 3.
- Produces: `read_ram_stats() -> tuple[float, float, int]` returning `(used_gb, total_gb, pct)` — used by Task 3.
- Produces: `get_ram_usage() -> str` — unchanged signature/behavior, still used by `build_stats_embed`.
- Produces: `should_auto_restart(pct, threshold_pct, last_restart_monotonic, now_monotonic, cooldown_min) -> bool` — pure function, used by Task 3.

- [ ] **Step 1: Add the new env vars**

In `main.py`, after the existing `ACTIVITY_CHANNEL_ID = int(os.environ["ACTIVITY_CHANNEL_ID"])` line (currently line 29), add:

```python
_ram_restart_threshold_env = os.environ.get("RAM_RESTART_THRESHOLD_PCT")
RAM_RESTART_THRESHOLD_PCT = float(_ram_restart_threshold_env) if _ram_restart_threshold_env else None
RAM_RESTART_COOLDOWN_MIN = float(os.environ.get("RAM_RESTART_COOLDOWN_MIN", "15"))
RAM_RESTART_WARNING_SEC = float(os.environ.get("RAM_RESTART_WARNING_SEC", "60"))
```

- [ ] **Step 2: Split `get_ram_usage()` into `read_ram_stats()` + `get_ram_usage()`**

Replace the current `get_ram_usage` (`main.py:109-122`):

```python
def get_ram_usage():
    # Bot runs on the same box as the game server, so read system memory
    # directly rather than via Palworld's REST API (which doesn't expose it).
    meminfo = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, value = line.split(":", 1)
            meminfo[key] = int(value.strip().split()[0])  # kB
    total_kb = meminfo["MemTotal"]
    available_kb = meminfo["MemAvailable"]
    used_gb = (total_kb - available_kb) / 1_048_576
    total_gb = total_kb / 1_048_576
    pct = round((used_gb / total_gb) * 100)
    return f"{used_gb:.1f}/{total_gb:.1f} GB ({pct}%)"
```

with:

```python
def read_ram_stats():
    # Bot runs on the same box as the game server, so read system memory
    # directly rather than via Palworld's REST API (which doesn't expose it).
    meminfo = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, value = line.split(":", 1)
            meminfo[key] = int(value.strip().split()[0])  # kB
    total_kb = meminfo["MemTotal"]
    available_kb = meminfo["MemAvailable"]
    used_gb = (total_kb - available_kb) / 1_048_576
    total_gb = total_kb / 1_048_576
    pct = round((used_gb / total_gb) * 100)
    return used_gb, total_gb, pct


def get_ram_usage():
    used_gb, total_gb, pct = read_ram_stats()
    return f"{used_gb:.1f}/{total_gb:.1f} GB ({pct}%)"
```

`build_stats_embed` (which calls `get_ram_usage()`) needs no changes — its call signature is untouched.

- [ ] **Step 3: Add the pure `should_auto_restart` helper**

Directly below the `get_ram_usage` function from Step 2, add:

```python
def should_auto_restart(pct, threshold_pct, last_restart_monotonic, now_monotonic, cooldown_min):
    if threshold_pct is None:
        return False
    if pct < threshold_pct:
        return False
    if last_restart_monotonic is None:
        return True
    return now_monotonic - last_restart_monotonic >= cooldown_min * 60
```

- [ ] **Step 4: Verify syntax**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0.

- [ ] **Step 5: Verify `should_auto_restart` logic in isolation**

Since `main.py` can't be imported without a full `.env`/Discord token, verify the pure function by copying it into a throwaway script and exercising it directly.

Create `C:\Users\byron\AppData\Local\Temp\claude\C--Users-byron-PycharmProjects-swee\f7489eaf-fafb-436b-aa0d-eece3c4f3225\scratchpad\test_should_auto_restart.py`:

```python
def should_auto_restart(pct, threshold_pct, last_restart_monotonic, now_monotonic, cooldown_min):
    if threshold_pct is None:
        return False
    if pct < threshold_pct:
        return False
    if last_restart_monotonic is None:
        return True
    return now_monotonic - last_restart_monotonic >= cooldown_min * 60


# Feature disabled (threshold unset)
assert should_auto_restart(95, None, None, 1000, 15) is False

# Under threshold
assert should_auto_restart(89, 90, None, 1000, 15) is False

# At/over threshold, no prior restart
assert should_auto_restart(90, 90, None, 1000, 15) is True
assert should_auto_restart(95, 90, None, 1000, 15) is True

# Over threshold, still in cooldown (10 min after a restart, 15 min cooldown)
assert should_auto_restart(95, 90, 1000, 1000 + 10 * 60, 15) is False

# Over threshold, cooldown elapsed (16 min after a restart, 15 min cooldown)
assert should_auto_restart(95, 90, 1000, 1000 + 16 * 60, 15) is True

# Exactly at cooldown boundary counts as elapsed
assert should_auto_restart(95, 90, 1000, 1000 + 15 * 60, 15) is True

print("all should_auto_restart cases passed")
```

Run: `python test_should_auto_restart.py` (from the scratchpad directory)
Expected output: `all should_auto_restart cases passed`

- [ ] **Step 6: Document the new env vars in `.env.example`**

Append to `.env.example`:

```
# Optional: automatically restart the palworld service when host RAM usage
# crosses this percentage. Leave unset to disable the feature entirely.
# RAM_RESTART_THRESHOLD_PCT=90
# RAM_RESTART_COOLDOWN_MIN=15
# RAM_RESTART_WARNING_SEC=60
```

- [ ] **Step 7: Commit**

```bash
git add main.py .env.example
git commit -m "Add RAM auto-restart config and threshold-decision helper"
```

---

### Task 2: Extract shared `restart_palworld()` helper

**Files:**
- Modify: `main.py:299-338` (`/restart` command)

**Interfaces:**
- Consumes: `rest.info()` (existing `PalRestClient` method), `COLOR_SHUTDOWN`, `COLOR_READY`, `COLOR_LEAVE` (existing module constants).
- Produces: `async def restart_palworld(on_progress=None) -> discord.Embed` — used by Task 3's `auto_restart_sequence`. `on_progress`, if given, is an `async def (status: str) -> None` callback invoked once, after the systemctl command completes, with the "waiting for server" status text — callers use it to edit an in-progress Discord message. Returns the final result embed (title "Server restarted" or "Restart timed out", with a single "Status" field), same content as the embed the `/restart` command builds today.

- [ ] **Step 1: Replace the `/restart` command body**

Replace `main.py:299-338`:

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

    proc = await asyncio.create_subprocess_exec("sudo", "systemctl", "restart", "palworld")
    await proc.wait()

    embed.set_field_at(0, name="Status", value="Waiting for server to come back online…")
    await interaction.edit_original_response(embed=embed)

    start = time.monotonic()
    timeout = 120
    online = False
    while time.monotonic() - start < timeout:
        try:
            await rest.info()
            online = True
            break
        except Exception:
            await asyncio.sleep(5)

    elapsed = int(time.monotonic() - start)
    if online:
        embed.title = "Server restarted"
        embed.color = COLOR_READY
        embed.set_field_at(0, name="Status", value=f"Back online after {elapsed}s")
    else:
        embed.title = "Restart timed out"
        embed.color = COLOR_LEAVE
        embed.set_field_at(
            0, name="Status",
            value=f"No response after {timeout}s — check `journalctl -u palworld`",
        )
    await interaction.edit_original_response(embed=embed)
```

with:

```python
async def restart_palworld(on_progress=None):
    proc = await asyncio.create_subprocess_exec("sudo", "systemctl", "restart", "palworld")
    await proc.wait()

    if on_progress:
        await on_progress("Waiting for server to come back online…")

    start = time.monotonic()
    timeout = 120
    online = False
    while time.monotonic() - start < timeout:
        try:
            await rest.info()
            online = True
            break
        except Exception:
            await asyncio.sleep(5)

    elapsed = int(time.monotonic() - start)
    embed = discord.Embed(color=COLOR_READY if online else COLOR_LEAVE)
    if online:
        embed.title = "Server restarted"
        embed.add_field(name="Status", value=f"Back online after {elapsed}s")
    else:
        embed.title = "Restart timed out"
        embed.add_field(
            name="Status",
            value=f"No response after {timeout}s — check `journalctl -u palworld`",
        )
    return embed


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

- [ ] **Step 2: Verify syntax**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Manual trace review (no test runner available)**

Read through the new `restart_palworld` and `restart` command side by side with the original body from Step 1 and confirm:
- The subprocess call, timeout (120s), poll interval (5s), and both result-embed branches (`online`/timed out) are byte-for-byte the same text as before.
- The `/restart` command still shows "Sending restart command…" immediately (from the initial `send_message`), then "Waiting for server to come back online…" (via `on_progress`), then the final result — the same three-stage sequence as before extraction.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "Extract restart_palworld() helper out of the /restart command"
```

---

### Task 3: Wire the auto-restart trigger into `stats_ticker`

**Files:**
- Modify: `main.py:104-107` (module-level state near the stats section)
- Modify: `main.py:181-185` (`stats_ticker`)

**Interfaces:**
- Consumes: `read_ram_stats()`, `should_auto_restart()`, `RAM_RESTART_THRESHOLD_PCT`, `RAM_RESTART_COOLDOWN_MIN`, `RAM_RESTART_WARNING_SEC` (Task 1), `restart_palworld()` (Task 2), `broadcast_embed()` (existing, `main.py:90`), `rest.announce()` (existing `PalRestClient` method), `bot.get_channel`, `ACTIVITY_CHANNEL_ID`, `COLOR_SHUTDOWN` (existing).
- Produces: `_last_auto_restart` (module-level, `float | None`, `time.monotonic()`-based) and `auto_restart_sequence(pct)` — internal to this task, not consumed elsewhere.

- [ ] **Step 1: Add the cooldown-tracking state**

In `main.py`, next to the existing stats-section state (`main.py:105-106`, `stats_message_id` / `_stats_lock`), add:

```python
_last_auto_restart = None  # time.monotonic() of the last auto-restart trigger, or None
```

- [ ] **Step 2: Add `auto_restart_sequence`**

Add this function near `stats_ticker` (e.g. directly above it, `main.py:181`):

```python
async def auto_restart_sequence(pct):
    warning_sec = int(RAM_RESTART_WARNING_SEC)
    await broadcast_embed(
        "High RAM usage detected",
        f"RAM usage at {pct}% — restarting server in {warning_sec}s.",
        COLOR_SHUTDOWN,
    )
    try:
        await rest.announce(f"Server restarting in {warning_sec}s due to high memory usage")
    except Exception:
        log.exception("in-game auto-restart announce failed")

    await asyncio.sleep(RAM_RESTART_WARNING_SEC)

    embed = await restart_palworld()
    channel = bot.get_channel(ACTIVITY_CHANNEL_ID)
    if isinstance(channel, discord.TextChannel):
        await channel.send(embed=embed)
    else:
        log.warning("auto-restart result broadcast failed: channel %s not found or not a text channel", ACTIVITY_CHANNEL_ID)
```

- [ ] **Step 3: Wire the trigger check into `stats_ticker`**

Replace the current `stats_ticker` (`main.py:181-185`):

```python
@tasks.loop(minutes=1)
async def stats_ticker():
    # Periodic tick for FPS/uptime, since those don't have a discrete log event.
    # Join/leave events also trigger an immediate update — see log_tailer below.
    await update_stats_message()
```

with:

```python
@tasks.loop(minutes=1)
async def stats_ticker():
    # Periodic tick for FPS/uptime, since those don't have a discrete log event.
    # Join/leave events also trigger an immediate update — see log_tailer below.
    await update_stats_message()

    if RAM_RESTART_THRESHOLD_PCT is None:
        return

    global _last_auto_restart
    try:
        _, _, pct = read_ram_stats()
    except Exception:
        log.exception("RAM read failed for auto-restart check")
        return

    now = time.monotonic()
    if should_auto_restart(pct, RAM_RESTART_THRESHOLD_PCT, _last_auto_restart, now, RAM_RESTART_COOLDOWN_MIN):
        _last_auto_restart = now
        asyncio.create_task(auto_restart_sequence(pct))
```

- [ ] **Step 4: Verify syntax**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0.

- [ ] **Step 5: Manual trace review (no test runner available)**

Re-read the full modified `stats_ticker` + `auto_restart_sequence` and confirm against the spec (`docs/superpowers/specs/2026-07-07-ram-auto-restart-design.md`):
- `_last_auto_restart` is set *before* `asyncio.create_task(...)`, not after the restart completes — so the cooldown window covers the warning delay and the restart itself.
- `asyncio.create_task` (not `await`) is used, so `stats_ticker` returns immediately and the next `update_stats_message()` tick isn't blocked by the 60s warning sleep.
- If `RAM_RESTART_THRESHOLD_PCT` is `None`, the function returns right after `update_stats_message()` — no RAM read, no trigger check at all.
- A failed `rest.announce()` in `auto_restart_sequence` is caught and logged, and does not prevent `restart_palworld()` from being called afterward.

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "Trigger auto-restart from stats_ticker when RAM crosses threshold"
```

---

### Task 4: Update README and manual smoke-test checklist

**Files:**
- Modify: `README.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Document the feature in the "How it works" section**

In `README.md`, after the existing "Stats embed" bullet (`README.md:13-15`), add a new bullet:

```markdown
- **RAM auto-restart** (optional) — if `RAM_RESTART_THRESHOLD_PCT` is set, the stats ticker
  restarts the `palworld` service whenever host RAM usage crosses that percentage. Players get
  a Discord activity-channel warning and an in-game announcement `RAM_RESTART_WARNING_SEC`
  (default 60s) before the restart fires, and a `RAM_RESTART_COOLDOWN_MIN` (default 15min)
  cooldown prevents repeat triggers while the server is still booting back up.
```

- [ ] **Step 2: Mention the new env vars in Setup**

In `README.md:28-29`, after "Fill in `.env` with your bot token, guild/channel/role IDs, and Palworld REST credentials, then", add a sentence:

```markdown
`RAM_RESTART_THRESHOLD_PCT` and its companions are optional — leave them unset to keep
auto-restart disabled.
```

- [ ] **Step 3: Verify docs render sensibly**

Read the edited sections of `README.md` back and confirm the new bullet/sentence fit the existing tone and don't duplicate information already stated elsewhere.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Document RAM auto-restart feature and its env vars"
```

---

## Post-plan manual smoke test (run on the actual Palworld host, not in this dev environment)

This cannot be automated here since `main.py` requires Linux, `/proc/meminfo`, `systemctl`, and a live Discord/Palworld REST connection. After deploying, verify on the real host:

1. Set `RAM_RESTART_THRESHOLD_PCT=1` (an artificially low threshold) and `RAM_RESTART_WARNING_SEC=10` in a test `.env`, restart the bot.
2. Within a minute, confirm: the activity channel gets the "High RAM usage detected" warning, the in-game chat gets the announcement, and ~10s later the server restarts and a result embed appears in the activity channel.
3. Confirm the bot does *not* trigger a second auto-restart within `RAM_RESTART_COOLDOWN_MIN` of the first, even though RAM is likely still elevated right after boot.
4. Reset `.env` to real thresholds (or unset `RAM_RESTART_THRESHOLD_PCT`) and confirm `/restart` still works standalone with its three-stage status message (Sending → Waiting → Restarted/Timed out).
