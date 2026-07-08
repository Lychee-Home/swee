# Alerts Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split shutdown, "server online", and RAM auto-restart warning/result messages out of the noisy `ACTIVITY_CHANNEL_ID` into a new dedicated `ALERTS_CHANNEL_ID`, leaving join/leave and chat relay on the existing activity channel.

**Architecture:** `broadcast_embed()` gains an optional `channel_id` parameter (default `ACTIVITY_CHANNEL_ID`, preserving every call site that doesn't pass it). The shutdown/version branches in `log_tailer()` and both sends in `auto_restart_sequence()` pass `channel_id=ALERTS_CHANNEL_ID` explicitly. A new required env var `ALERTS_CHANNEL_ID` is parsed alongside the existing channel IDs.

**Tech Stack:** Python 3.13, discord.py (no new dependencies).

## Global Constraints

- No automated test suite exists in this repo — verification is manual/read-back plus `python -m py_compile main.py`; full behavioral testing requires the Linux host with a live Discord bot token and real channels (per `CLAUDE.md` and the prior plan's precedent).
- All bot logic lives in `main.py`; do not split into modules.
- `ALERTS_CHANNEL_ID` is **required**, parsed the same way as the other channel IDs: `int(os.environ["ALERTS_CHANNEL_ID"])`, no default.
- `check_palworld_service()` is explicitly out of scope — do not touch it.
- Join/leave branches in `log_tailer()` and the chat relay in `on_message()` must remain unchanged, still targeting `ACTIVITY_CHANNEL_ID`.

---

### Task 1: Add `ALERTS_CHANNEL_ID` config and route alert-worthy messages to it

**Files:**
- Modify: `main.py` (config block ~line 20-29, `broadcast_embed()` ~line 95-106, `log_tailer()` ~line 304-309, `auto_restart_sequence()` ~line 204-230)
- Modify: `.env.example` (add `ALERTS_CHANNEL_ID` alongside the other channel IDs)
- Modify: `README.md` (document the new channel in the channel list / setup section)

**Interfaces:**
- Produces: `broadcast_embed(title, description, color, dt=None, channel_id=ACTIVITY_CHANNEL_ID)` — existing callers (join/leave in `log_tailer()`) are unaffected since the new parameter defaults to the old hardcoded value.
- Produces: module-level `ALERTS_CHANNEL_ID: int`, parsed the same way as `ACTIVITY_CHANNEL_ID`.

- [ ] **Step 1: Add `ALERTS_CHANNEL_ID` to the config block**

Current (main.py:20-29):

```python
GUILD_ID          = int(os.environ["GUILD_ID"])
RELAY_CHANNEL_ID  = int(os.environ["RELAY_CHANNEL_ID"])
STATS_CHANNEL_ID  = int(os.environ["STATS_CHANNEL_ID"])
ADMIN_ROLE_ID     = int(os.environ["ADMIN_ROLE_ID"])
BOT_TOKEN         = os.environ["DISCORD_BOT_TOKEN"]

REST_BASE = f"http://{os.environ['REST_HOST']}:{os.environ['REST_PORT']}/v1/api"
REST_AUTH = httpx.BasicAuth(os.environ["REST_USER"], os.environ["REST_PASSWORD"])

ACTIVITY_CHANNEL_ID = int(os.environ["ACTIVITY_CHANNEL_ID"])
```

New — add the line directly after `ACTIVITY_CHANNEL_ID`:

```python
GUILD_ID          = int(os.environ["GUILD_ID"])
RELAY_CHANNEL_ID  = int(os.environ["RELAY_CHANNEL_ID"])
STATS_CHANNEL_ID  = int(os.environ["STATS_CHANNEL_ID"])
ADMIN_ROLE_ID     = int(os.environ["ADMIN_ROLE_ID"])
BOT_TOKEN         = os.environ["DISCORD_BOT_TOKEN"]

REST_BASE = f"http://{os.environ['REST_HOST']}:{os.environ['REST_PORT']}/v1/api"
REST_AUTH = httpx.BasicAuth(os.environ["REST_USER"], os.environ["REST_PASSWORD"])

ACTIVITY_CHANNEL_ID = int(os.environ["ACTIVITY_CHANNEL_ID"])
ALERTS_CHANNEL_ID   = int(os.environ["ALERTS_CHANNEL_ID"])
```

- [ ] **Step 2: Add `channel_id` parameter to `broadcast_embed()`**

Current (main.py:95-106):

```python
async def broadcast_embed(title, description, color, dt=None):
    embed = discord.Embed(title=title, description=description, color=color)
    if dt:
        embed.timestamp = dt
    channel = bot.get_channel(ACTIVITY_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        log.warning("broadcast failed: channel %s not found or not a text channel", ACTIVITY_CHANNEL_ID)
        return
    try:
        await channel.send(embed=embed)
    except Exception:
        log.exception("broadcast failed")
```

New:

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

- [ ] **Step 3: Route `log_tailer()`'s shutdown/version branches to the alerts channel**

Current (main.py:304-309):

```python
                else:
                    if SHUTDOWN_RE.search(msg):
                        await broadcast_embed("Server shutting down", None, COLOR_SHUTDOWN, dt)
                    elif m := VERSION_RE.search(msg):
                        if not _auto_restart_in_progress:
                            await broadcast_embed("Server is online", f"Game version: `{m.group(1)}`", COLOR_READY, dt)
```

New:

```python
                else:
                    if SHUTDOWN_RE.search(msg):
                        await broadcast_embed("Server shutting down", None, COLOR_SHUTDOWN, dt, channel_id=ALERTS_CHANNEL_ID)
                    elif m := VERSION_RE.search(msg):
                        if not _auto_restart_in_progress:
                            await broadcast_embed("Server is online", f"Game version: `{m.group(1)}`", COLOR_READY, dt, channel_id=ALERTS_CHANNEL_ID)
```

The `JOIN_RE`/`LEAVE_RE` branches directly above this block (main.py:298-303) are **not** touched — they keep calling `broadcast_embed(...)` with no `channel_id`, so they still default to `ACTIVITY_CHANNEL_ID`.

- [ ] **Step 4: Route `auto_restart_sequence()`'s warning and result messages to the alerts channel**

Current (main.py:204-230):

```python
async def auto_restart_sequence(pct):
    global _auto_restart_in_progress
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

    _auto_restart_in_progress = True
    try:
        embed = await restart_palworld()
    finally:
        _auto_restart_in_progress = False

    channel = bot.get_channel(ACTIVITY_CHANNEL_ID)
    if isinstance(channel, discord.TextChannel):
        await channel.send(embed=embed)
    else:
        log.warning("auto-restart result broadcast failed: channel %s not found or not a text channel", ACTIVITY_CHANNEL_ID)
```

New:

```python
async def auto_restart_sequence(pct):
    global _auto_restart_in_progress
    warning_sec = int(RAM_RESTART_WARNING_SEC)
    await broadcast_embed(
        "High RAM usage detected",
        f"RAM usage at {pct}% — restarting server in {warning_sec}s.",
        COLOR_SHUTDOWN,
        channel_id=ALERTS_CHANNEL_ID,
    )
    try:
        await rest.announce(f"Server restarting in {warning_sec}s due to high memory usage")
    except Exception:
        log.exception("in-game auto-restart announce failed")

    await asyncio.sleep(RAM_RESTART_WARNING_SEC)

    _auto_restart_in_progress = True
    try:
        embed = await restart_palworld()
    finally:
        _auto_restart_in_progress = False

    channel = bot.get_channel(ALERTS_CHANNEL_ID)
    if isinstance(channel, discord.TextChannel):
        await channel.send(embed=embed)
    else:
        log.warning("auto-restart result broadcast failed: channel %s not found or not a text channel", ALERTS_CHANNEL_ID)
```

- [ ] **Step 5: Update `.env.example`**

Read `.env.example` first to find where `ACTIVITY_CHANNEL_ID` is listed (it's organized into labeled sections per the repo's recent "Organize .env.example into labeled sections" commit). Add `ALERTS_CHANNEL_ID` immediately after `ACTIVITY_CHANNEL_ID` in the same section, following the file's existing formatting/comment style for that section exactly (matching indentation, comment style, and whether values are blank or placeholder IDs).

- [ ] **Step 6: Update `README.md`**

Read `README.md`'s "How it works" section (currently documents `ACTIVITY_CHANNEL_ID` around the "journalctl" and "RAM auto-restart" bullets, main.py's README lines ~9-22). Add a short mention of `ALERTS_CHANNEL_ID`: it receives server shutdown, server-online, and RAM auto-restart warning/result messages, while `ACTIVITY_CHANNEL_ID` continues to carry join/leave and chat relay. Keep it concise and match the existing bullet-point style — don't restructure the section.

- [ ] **Step 7: Verify**

There's no automated test suite. Run:

```bash
python -m py_compile main.py
```

Expected: no output (success). Then read back all four changed locations in `main.py` (config block, `broadcast_embed`, `log_tailer`, `auto_restart_sequence`) to confirm:
- `ALERTS_CHANNEL_ID` is parsed via `int(os.environ["ALERTS_CHANNEL_ID"])`.
- `broadcast_embed`'s new parameter defaults to `ACTIVITY_CHANNEL_ID` and both join/leave call sites are unchanged (no `channel_id` argument).
- Both `log_tailer` shutdown/version calls and both `auto_restart_sequence` sends (warning broadcast + result channel fetch) use `ALERTS_CHANNEL_ID`.

Full behavioral verification (actually seeing messages land in the right Discord channels) requires the Linux host with a live bot token and both channels created — out of scope for this environment; note this in the report, matching how the prior `palworld-service-check` plan handled Linux-only verification steps.

- [ ] **Step 8: Commit**

```bash
git add main.py .env.example README.md
git commit -m "$(cat <<'EOF'
Add dedicated alerts channel for shutdown, online, and auto-restart events

Splits higher-signal operational events (server shutdown, server online,
RAM auto-restart warning/result) out of the noisy activity channel into
a new required ALERTS_CHANNEL_ID, so admins can watch one channel for
events that need attention without the join/leave and chat noise.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Post-plan note

`check_palworld_service()` is unchanged by this plan — it remains log-only with no Discord
dependency, per the earlier design decision. No other files need updates: `docs/superpowers/`
already documents the spec+plan convention generally in `CLAUDE.md`.
