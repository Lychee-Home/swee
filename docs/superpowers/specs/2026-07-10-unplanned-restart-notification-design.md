# Unplanned restart notification — design

## Problem

The Palworld service can restart for reasons outside the bot's control — e.g. `needrestart`
cycling the service after `unattended-upgrades` patches a linked library (this happened on
2026-07-10: a libcurl security update triggered `needrestart` to restart `palworld.service`
5 seconds after the package install). Today the log tailer posts a generic "Server shutting
down" message for *every* shutdown, whether triggered by `/restart`, the RAM auto-restart, or
something external — giving no indication that this one wasn't intentional, and no explanation
of why it happened.

## Scope

- Distinguish "planned" shutdowns (triggered by `/restart` or the RAM auto-restart) from
  "unplanned" ones (everything else — host-level restarts, crashes, `needrestart`, etc.).
- For unplanned shutdowns, post a distinct Discord embed to `ALERTS_CHANNEL_ID` and attempt to
  explain the cause via a small, extensible set of cause detectors.
- First detector: recognize an `unattended-upgrades` package install immediately preceding the
  restart (the `needrestart` pattern from the 2026-07-10 incident).
- Detector output and all user-facing text must be in plain language — no Linux commands, log
  paths, or package names surfaced to Discord.
- Notification is Discord-only; no in-game broadcast for unplanned restarts.

Out of scope: automated remediation, notifying about crashes with no known cause beyond
"unknown", any detector beyond the unattended-upgrades one (future causes get added later as
they come up, per the extensible registry below).

## Components

### 1. Shared "planned restart" flag

Rename `_auto_restart_in_progress` → `_bot_restart_in_progress`. It continues to be set/cleared
around `restart_palworld()` in `auto_restart_sequence()` (unchanged behavior), and is newly also
set/cleared around the `/restart` command's call to `restart_palworld()`:

```python
@bot.tree.command(description="Restart the Palworld service")
@is_admin()
async def restart(interaction: discord.Interaction):
    ...
    global _bot_restart_in_progress
    _bot_restart_in_progress = True
    try:
        result_embed = await restart_palworld(on_progress)
    finally:
        _bot_restart_in_progress = False
    await interaction.edit_original_response(embed=result_embed)
```

This incidentally fixes an existing bug: `/restart` currently doesn't set this flag, so the log
tailer's `VERSION_RE` handler (guarded by `if not _auto_restart_in_progress`) double-posts
"Server is online" during a manual restart, in addition to the `/restart` command's own result
embed. With the shared flag, that suppression now correctly covers both restart paths.

### 2. Branch in `log_tailer()` on `SHUTDOWN_RE` match

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

(`broadcast_embed` gains an optional `fields` parameter to attach extra embed fields; existing
callers that don't pass it are unaffected.)

### 3. Cause-detector registry

```python
CauseDetector = Callable[[datetime], Awaitable[str | None]]

CAUSE_DETECTORS: list[CauseDetector] = [
    detect_unattended_upgrades,
]

async def detect_unplanned_restart_cause(shutdown_dt: datetime) -> str | None:
    for detector in CAUSE_DETECTORS:
        try:
            if result := await detector(shutdown_dt):
                return result
        except Exception:
            log.exception("cause detector %s failed", detector.__name__)
    return None
```

To add a future cause, write one more `async def detect_x(dt: datetime) -> str | None` function
and append it to `CAUSE_DETECTORS`. No other code changes needed. Detectors run in list order;
the first non-`None` result wins.

### 4. `detect_unattended_upgrades` detector

```python
UNATTENDED_UPGRADES_LOG = "/var/log/unattended-upgrades/unattended-upgrades.log"
UPGRADE_LOG_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO Packages that will be upgraded: (.+)$'
)

async def detect_unattended_upgrades(shutdown_dt: datetime) -> str | None:
    try:
        lines = await asyncio.to_thread(_read_last_lines, UNATTENDED_UPGRADES_LOG, 100)
    except OSError:
        return None

    for line in reversed(lines):
        m = UPGRADE_LOG_RE.match(line)
        if not m:
            continue
        ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        delta = (shutdown_dt.astimezone(timezone.utc) - ts).total_seconds()
        if -30 <= delta <= 120:
            return "A routine system update installed a security patch that caused a restart."
        break  # most recent entry too far from the shutdown time — no match
    return None
```

`_read_last_lines(path, n)` is a small sync helper (`Path(path).read_text().splitlines()[-n:]`)
run off the event loop via `asyncio.to_thread`, since it's a blocking file read happening during
live log-tailing.

Window is `[-30s, +120s]` relative to the shutdown timestamp: the upgrade log entry precedes the
shutdown (observed gap was ~2s in the 2026-07-10 incident), with slack for slower installs.

## Error handling

- Missing/unreadable log file, unparsable lines, or any other detector exception: caught,
  logged, treated as "no match" — the notification still posts with "cause unknown," never
  blocks or crashes the log tailer.
- `broadcast_embed` failures (channel not found, etc.) already log a warning today; unchanged.

## Non-goals / risks accepted

- No attempt to detect OOM-kills, crashes, or other causes in this pass — the registry makes
  adding them later a small, isolated change.
- The detector reads a specific, distro-default log path; if a host's unattended-upgrades log
  lives elsewhere, this detector silently never matches (degrades to "unknown," not an error).
- Time-window matching is heuristic — a coincidental package upgrade in the same window as an
  unrelated restart would be misattributed. Accepted given how narrow the window is and how
  rare unrelated restarts are.
