# Alerts channel for auto-restart, shutdown, and online events — design

## Problem

`ACTIVITY_CHANNEL_ID` currently carries every kind of server event: routine join/leave
activity, the relayed chat feed, and higher-signal operational events (server shutting down,
server back online with version, and RAM-triggered auto-restart warnings/results). Mixing
routine activity with operationally significant events makes the channel noisy and makes it
harder for admins to notice the events that actually need attention. We want to split the
higher-signal events into a dedicated alerts channel.

## Scope

New required environment variable `ALERTS_CHANNEL_ID`, parsed the same way as the existing
channel IDs (`int(os.environ["ALERTS_CHANNEL_ID"])`, no default — matches
`GUILD_ID`/`RELAY_CHANNEL_ID`/`STATS_CHANNEL_ID`/`ACTIVITY_CHANNEL_ID`).

Messages moving from `ACTIVITY_CHANNEL_ID` to `ALERTS_CHANNEL_ID`:
- RAM auto-restart warning ("High RAM usage detected... restarting in Ns") — `auto_restart_sequence()`.
- RAM auto-restart result ("Server restarted" / "Restart timed out") — `auto_restart_sequence()`.
- Server shutdown ("Server shutting down") — `log_tailer()`, `SHUTDOWN_RE` branch.
- Server online ("Server is online", game version) — `log_tailer()`, `VERSION_RE` branch.

Staying on `ACTIVITY_CHANNEL_ID`, unchanged:
- Join/leave events — `log_tailer()`, `JOIN_RE`/`LEAVE_RE` branches.
- Discord→game chat relay — `on_message()` (doesn't post to a channel; it's the reverse
  direction, posts to the game via REST).
- The `/restart` slash command's own response — this is an ephemeral interaction reply, not
  a channel post, so it's unaffected regardless of which channel auto-restart uses.

Out of scope:
- `check_palworld_service()` (the startup precondition check) stays exactly as-is — log-only,
  no Discord dependency, since it runs before the bot connects at all. This is deliberate,
  matching the earlier design decision in
  `docs/superpowers/specs/2026-07-08-palworld-service-check-design.md`.
- No fallback or auto-creation if `ALERTS_CHANNEL_ID` resolves to a missing/non-text channel —
  reuses the existing `broadcast_embed()` guard (log a warning, skip the send).
- No change to `STATS_CHANNEL_ID` or the pinned stats embed.

## Configuration

| Var | Default | Meaning |
|---|---|---|
| `ALERTS_CHANNEL_ID` | required, no default | Channel for shutdown, online, and RAM auto-restart warning/result messages |

Added to `.env.example` alongside the other channel IDs, and documented in `README.md`'s
channel list.

## Implementation

### 1. `broadcast_embed()` gains an optional `channel_id` parameter

Currently hardcoded to `ACTIVITY_CHANNEL_ID` (main.py:95-106). Add a `channel_id` parameter
defaulting to `ACTIVITY_CHANNEL_ID`, so every call site that doesn't pass it explicitly
(join/leave) is unaffected:

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

### 2. `log_tailer()` shutdown/version branches pass `channel_id=ALERTS_CHANNEL_ID`

Current (main.py:304-309):

```python
if SHUTDOWN_RE.search(msg):
    await broadcast_embed("Server shutting down", None, COLOR_SHUTDOWN, dt)
elif m := VERSION_RE.search(msg):
    if not _auto_restart_in_progress:
        await broadcast_embed("Server is online", f"Game version: `{m.group(1)}`", COLOR_READY, dt)
```

New:

```python
if SHUTDOWN_RE.search(msg):
    await broadcast_embed("Server shutting down", None, COLOR_SHUTDOWN, dt, channel_id=ALERTS_CHANNEL_ID)
elif m := VERSION_RE.search(msg):
    if not _auto_restart_in_progress:
        await broadcast_embed("Server is online", f"Game version: `{m.group(1)}`", COLOR_READY, dt, channel_id=ALERTS_CHANNEL_ID)
```

Join/leave branches (main.py:298-303) are untouched — they keep calling `broadcast_embed(...)`
without `channel_id`, so they keep defaulting to `ACTIVITY_CHANNEL_ID`.

### 3. `auto_restart_sequence()` targets the alerts channel

Current (main.py:204-230): the warning uses `broadcast_embed(...)` (implicitly
`ACTIVITY_CHANNEL_ID`), and the result embed is sent via a separate inline
`bot.get_channel(ACTIVITY_CHANNEL_ID)` block.

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

### 4. New config parse

Alongside the other channel IDs (main.py:20-29):

```python
ALERTS_CHANNEL_ID = int(os.environ["ALERTS_CHANNEL_ID"])
```

## Error handling

No new error handling needed — every changed call site reuses `broadcast_embed()`'s existing
guard (log a warning, skip the send if the channel is missing or not a text channel) or the
same inline pattern already used for `ACTIVITY_CHANNEL_ID` in `auto_restart_sequence()`.

## Non-goals / risks accepted

- `ALERTS_CHANNEL_ID` is required, not optional — existing deployments must add it to `.env`
  and create the channel before upgrading, or the bot fails at startup with a `KeyError` (same
  behavior as any other missing required env var today).
- No migration path that reuses `ACTIVITY_CHANNEL_ID` as a fallback if `ALERTS_CHANNEL_ID` is
  unset — deliberate, to keep config parsing consistent with the rest of the file.
- `check_palworld_service()` remains completely out of scope for this change, since it runs
  before Discord connects and reporting its failures to Discord was explicitly rejected in the
  earlier design.
