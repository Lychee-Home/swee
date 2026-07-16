# `/update` admin command — design

## Problem

There is no way to update the Palworld dedicated server binary through the bot. Today an admin
updates it manually by signing in as the `steam` user (the same user the bot runs as) and running:

```
/usr/games/steamcmd +force_install_dir /home/steam/palworld/pal-chuds +login anonymous +app_update 2394010 validate +quit
```

This requires host shell access and is easy to forget to pair with a save/stop/restart around it.
We want an admin-only Discord command that does the whole sequence safely, following the same
pattern as the existing `/restart` command.

## Scope

- New `/update` slash command, admin-only (`@is_admin()`), that: saves the world, stops the
  Palworld service, runs `steamcmd` to update/validate the install, starts the service back up,
  and reports the outcome — mirroring `restart.py` / the `/restart` command's structure and
  progress-embed UX.
- New config: `PALWORLD_INSTALL_DIR` (required) and `STEAMCMD_PATH` (optional, default
  `/usr/games/steamcmd`).
- Reuses the existing `_bot_restart_in_progress` flag so `log_tailer` treats the update's shutdown
  as planned, not an "unexpected restart."

Out of scope:
- Privilege escalation / sudoers changes — the bot already runs as the same `steam` user that runs
  steamcmd manually today, so no new sudo rule is needed beyond the existing
  `systemctl stop/start <service>` rule `/restart` already relies on.
- Parsing steamcmd output to determine whether a new version was actually installed vs. already
  up to date — `log_tailer` already announces the running version via its existing "Server is
  online" message once the service comes back up, so the update embed doesn't need to duplicate
  that.
- Scheduling/automatic updates — this is a manually triggered command only.

## Components

### 1. `swee/config.py` — new config constants

```python
PALWORLD_INSTALL_DIR = os.environ["PALWORLD_INSTALL_DIR"]
STEAMCMD_PATH = os.environ.get("STEAMCMD_PATH", "/usr/games/steamcmd")
```

Palworld's Steam App ID (`2394010`) is not configurable — it's a constant in `server_update.py`,
since it's fixed for this game.

### 2. `.env.example` — document the new vars

```
# --- Palworld server update ---
# Absolute path steamcmd installs/updates the Palworld dedicated server into
# (passed as +force_install_dir). Must match the install used by PALWORLD_SERVICE_NAME.
PALWORLD_INSTALL_DIR=/home/steam/palworld/pal-chuds
# Path to the steamcmd binary. Defaults to /usr/games/steamcmd (apt install location) if unset.
# STEAMCMD_PATH=/usr/games/steamcmd
```

Added as a new section near the existing "Palworld service" section.

### 3. `swee/server_update.py` — new module (mirrors `restart.py`)

```python
async def update_palworld(on_progress=None):
```

Sequence:

1. Best-effort `await rest.save()`, wrapped in `try`/`except Exception` with a `log.exception`
   fallback (same pattern `status`'s player-fetch uses) — a failed save shouldn't block the update.
2. `on_progress("Stopping server…")`; set `restart_module._bot_restart_in_progress = True`;
   `await asyncio.create_subprocess_exec("sudo", "systemctl", "stop", PALWORLD_SERVICE_NAME)` and
   wait for it.
3. `on_progress("Updating via steamcmd… this can take a few minutes")`; run steamcmd:
   ```python
   proc = await asyncio.create_subprocess_exec(
       STEAMCMD_PATH,
       "+force_install_dir", PALWORLD_INSTALL_DIR,
       "+login", "anonymous",
       "+app_update", "2394010", "validate",
       "+quit",
       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
   )
   stdout, _ = await proc.communicate()
   steamcmd_ok = proc.returncode == 0
   ```
   No timeout — steamcmd's own progress is the only signal of liveness and updates can
   legitimately take several minutes on a slow connection, same as how `/restart` doesn't time out
   the `systemctl restart` step itself (only the post-start online-wait, next step).
4. `on_progress("Starting server…")`; run
   `sudo systemctl start <PALWORLD_SERVICE_NAME>`, then poll `rest.info()` in a loop identical to
   `restart_palworld`'s (5s interval, 120s total timeout) to determine `online`.
5. Clear `restart_module._bot_restart_in_progress = False` in a `finally`.
6. Build and return a result `discord.Embed`:
   - Title `"Server updated"` (color `COLOR_READY`) if `steamcmd_ok and online`.
   - Title `"Update failed"` (color `COLOR_LEAVE`) if steamcmd failed — body includes the last
     ~500 chars of steamcmd's combined output (Discord field values cap at 1024 chars; truncate
     with a leading `"…"` marker if cut) so the admin can see the error without shelling in, plus
     a note that the service was still restarted regardless of steamcmd's outcome (matches the
     "don't leave the server down" behavior below).
   - Title `"Update timed out"` (color `COLOR_LEAVE`) if steamcmd succeeded but the service didn't
     come back online in time — same message style as `/restart`'s timeout case: "check
     `journalctl -u {PALWORLD_SERVICE_NAME}`".

Error handling: regardless of `steamcmd_ok`, step 4 (start + wait) always runs — an update that
fails to download shouldn't leave the server offline; the previously-installed files are still on
disk since `validate` only touches files it's replacing.

### 4. `swee/commands.py` — `/update` command

```python
@bot.tree.command(description="Update the Palworld server via steamcmd")
@is_admin()
async def update(interaction: discord.Interaction):
    embed = discord.Embed(title="Updating Palworld server", color=COLOR_SHUTDOWN)
    embed.add_field(name="Status", value="Saving world…")
    await interaction.response.send_message(embed=embed)

    async def on_progress(status):
        embed.set_field_at(0, name="Status", value=status)
        await interaction.edit_original_response(embed=embed)

    result_embed = await update_palworld(on_progress)
    await interaction.edit_original_response(embed=result_embed)
```

Same shape as the existing `restart` command (`swee/commands.py:74-93`); imports
`update_palworld` from the new `server_update` module.

## Testing

No Discord-command test harness exists in this repo (per `CLAUDE.md`) — `/restart` itself has none
either. This will be verified manually against the real server, the same way `/restart` was:
trigger `/update`, confirm the progress embed updates through each stage, confirm the server comes
back online, confirm `log_tailer` posts "Server is online" (not "restarted unexpectedly") once it
does, and confirm a deliberately-broken `PALWORLD_INSTALL_DIR` produces a clear "Update failed"
embed with steamcmd's error output.

## Non-goals / risks accepted

- If steamcmd itself hangs indefinitely (e.g. network stall mid-download with no output), the
  command has no timeout on that step and will appear stuck until the admin notices and restarts
  the bot. Accepted for now, consistent with `/restart` not timing out `systemctl restart` either;
  can be revisited if it turns out to be a real problem.
- `PALWORLD_INSTALL_DIR` is trusted, unvalidated input from `.env` — if it's misconfigured (wrong
  path, or a path steamcmd can't write to), the failure surfaces via steamcmd's non-zero exit and
  captured output in the "Update failed" embed rather than a friendlier pre-check. Consistent with
  how `PALWORLD_SETTINGS_INI_PATH` is handled elsewhere in the codebase (no existence check at
  startup).
