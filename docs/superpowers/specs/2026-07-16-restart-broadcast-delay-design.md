# Warn-and-delay for /restart and /update

## Problem

The RAM auto-restart path (`auto_restart_sequence` in `swee/restart.py`) already warns players
before restarting: it posts an embed to `ALERTS_CHANNEL_ID`, sends an in-game `rest.announce()`,
waits `RAM_RESTART_WARNING_SEC`, then restarts. The admin-triggered `/restart` and `/update`
slash commands do not — they restart (or stop, in `/update`'s case) immediately, giving online
players no notice.

## Design

### Shared helper

Extract the broadcast+announce+delay sequence out of `auto_restart_sequence` into a reusable
coroutine in `swee/restart.py`:

```python
async def warn_and_wait(discord_title, discord_description, ingame_message):
    warning_sec = int(RAM_RESTART_WARNING_SEC)
    await broadcast_embed(discord_title, discord_description, COLOR_SHUTDOWN, channel_id=ALERTS_CHANNEL_ID)
    try:
        await rest.announce(ingame_message)
    except Exception:
        log.exception("in-game restart announce failed")
    await asyncio.sleep(warning_sec)
```

`auto_restart_sequence` is rewritten to call `warn_and_wait` with its existing wording instead of
inlining the sequence. No behavior change for the RAM auto-restart path.

### `/restart` command

In `commands.py`, before calling `restart_palworld`, call:

```python
await warn_and_wait(
    "Restarting server",
    f"Restarting server in {warning_sec}s (requested by admin).",
    f"Server restarting in {warning_sec}s",
)
```

The command's response embed gains a progress step: `"Broadcasting restart warning…"` is shown
while `warn_and_wait` runs, then the existing `"Sending restart command…"` step proceeds as
before.

### `/update` command

`update_palworld` (`swee/server_update.py`) calls the same helper as its first action, before
"Saving world…":

```python
await warn_and_wait(
    "Updating server",
    f"Updating server — restarting in {warning_sec}s for an update.",
    f"Server restarting in {warning_sec}s for an update",
)
```

This delays the save/stop/steamcmd/start sequence by `RAM_RESTART_WARNING_SEC`, so players get
the same warning window as a plain restart before the world is saved and the service stopped.
`on_progress` gains a `"Broadcasting update warning…"` step first.

### Config

No new env var — `RAM_RESTART_WARNING_SEC` (default 60s) now governs the delay for all three
restart paths (RAM auto-restart, `/restart`, `/update`). Update the `.env.example` comment to
describe the broader scope.

### Failure handling

Same as the existing auto-restart path: if `rest.announce()` fails (e.g. the Palworld REST API
is unreachable), log and continue with the delay and restart/update rather than aborting.

## Out of scope

- No new configuration for a separate manual-restart delay.
- No change to the auto-restart's own wording or channel targets.
