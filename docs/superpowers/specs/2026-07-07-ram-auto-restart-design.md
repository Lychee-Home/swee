# RAM-triggered auto-restart — design

## Problem

The Palworld server occasionally runs into memory pressure that degrades or crashes it.
Today the only fix is a human noticing and running `/restart`. We want the bot to detect
high RAM usage itself and restart the `palworld` service automatically, while still giving
players a heads-up first.

## Scope

- Opt-in feature: disabled unless `RAM_RESTART_THRESHOLD_PCT` is set in `.env`.
- Threshold is a percentage of total system RAM (matches the stat already shown in the
  live stats embed via `get_ram_usage()`).
- Checked on the existing 1-minute `stats_ticker` loop — no new polling loop.
- On trigger: warn in Discord activity channel and in-game, wait a configurable delay,
  then restart unconditionally (no re-check), reusing the same restart-and-wait-for-online
  logic as the `/restart` slash command.
- Cooldown after a trigger prevents re-triggering while the server is mid-restart/booting
  (RAM is often still high right after boot while the world loads).

Out of scope: absolute-GB thresholds, canceling an in-flight warning if RAM recovers,
per-restart alerting/metrics beyond the existing Discord broadcasts.

## Configuration

New environment variables, all optional:

| Var | Default | Meaning |
|---|---|---|
| `RAM_RESTART_THRESHOLD_PCT` | unset (feature disabled) | RAM usage percentage that triggers an auto-restart |
| `RAM_RESTART_COOLDOWN_MIN` | `15` | Minutes to suppress further auto-restarts after one triggers |
| `RAM_RESTART_WARNING_SEC` | `60` | Delay between the warning broadcast and the actual restart |

If `RAM_RESTART_THRESHOLD_PCT` is unset, none of this code path runs — the feature is fully
inert, matching how the rest of the bot treats optional behavior.

## Components

### 1. `get_ram_usage()` refactor

Currently returns only a formatted display string. It will be split so the raw percentage
is available to the threshold check without re-parsing `/proc/meminfo` or the string:

```python
def read_ram_stats():
    # returns (used_gb, total_gb, pct) — the numbers get_ram_usage() currently formats
    ...

def get_ram_usage():
    used_gb, total_gb, pct = read_ram_stats()
    return f"{used_gb:.1f}/{total_gb:.1f} GB ({pct}%)"
```

`build_stats_embed` keeps calling `get_ram_usage()` unchanged. The ticker will call
`read_ram_stats()` directly for the threshold comparison.

### 2. Shared restart helper

The body of the `/restart` command (systemctl restart, poll `rest.info()` until online or
timeout, build a result embed) is extracted into:

```python
async def restart_palworld(reason: str) -> discord.Embed:
    # returns the same "Server restarted" / "Restart timed out" embed
    # currently built inline in the /restart command
```

- `/restart` command: calls `restart_palworld("manual")`, sends the returned embed as the
  interaction response (unchanged user-facing behavior — same messages/timing as today).
- Auto-restart path: calls `restart_palworld("high RAM usage")`, sends the returned embed
  to the activity channel via `channel.send(embed=...)` instead of an interaction response.

### 3. Auto-restart trigger

Inside `stats_ticker`, after computing `used_gb, total_gb, pct = read_ram_stats()`:

```python
if RAM_RESTART_THRESHOLD_PCT is not None and pct >= RAM_RESTART_THRESHOLD_PCT:
    now = time.monotonic()
    if _last_auto_restart is None or now - _last_auto_restart >= RAM_RESTART_COOLDOWN_MIN * 60:
        _last_auto_restart = now  # set immediately: covers the warning delay + restart itself
        asyncio.create_task(auto_restart_sequence(pct))
```

Setting the cooldown timestamp *before* spawning the task (rather than after the restart
completes) is deliberate: it prevents a second trigger firing during the warning delay or
the restart-and-poll window, without needing a separate "in progress" flag.

Spawning via `asyncio.create_task` (rather than `await`-ing inline) keeps the 1-minute
ticker loop from blocking for the warning delay, so the stats embed keeps refreshing on
schedule during the wait.

### 4. Warning + restart sequence

```python
async def auto_restart_sequence(pct):
    await broadcast_embed(
        "High RAM usage detected",
        f"RAM usage at {pct}% — restarting server in {RAM_RESTART_WARNING_SEC}s.",
        COLOR_SHUTDOWN,
    )
    try:
        await rest.announce(f"Server restarting in {RAM_RESTART_WARNING_SEC}s due to high memory usage")
    except Exception:
        log.exception("in-game auto-restart announce failed")

    await asyncio.sleep(RAM_RESTART_WARNING_SEC)

    embed = await restart_palworld("high RAM usage")
    channel = bot.get_channel(ACTIVITY_CHANNEL_ID)
    if isinstance(channel, discord.TextChannel):
        await channel.send(embed=embed)
```

The in-game announce is best-effort: if the REST API is already unresponsive due to memory
pressure, the restart still proceeds — only the courtesy warning is skipped.

## Error handling

- `read_ram_stats()` failure (e.g. `/proc/meminfo` unreadable): caught the same way
  `get_ram_usage()` failures are already caught in `build_stats_embed` — logged, threshold
  check skipped for that tick, retried next minute.
- `rest.announce()` failure during the warning: caught and logged, does not block the
  restart.
- `restart_palworld()` itself already has the existing timeout/online-check behavior from
  `/restart`; no new error handling needed beyond what's extracted.

## Non-goals / risks accepted

- No cancellation if RAM happens to drop during the warning window — once triggered, the
  restart happens. This avoids ambiguous "false alarm" messaging to players.
- If the bot process restarts during the warning delay (e.g. host reboot), the pending
  `auto_restart_sequence` task is lost with it — acceptable, since a fresh RAM reading on
  the next tick will re-trigger if the condition still holds (subject to no cooldown state
  surviving the bot restart either, which mirrors how `stats_message_id` already resets on
  bot restart).
