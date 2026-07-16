# `/update` admin command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin-only `/update` Discord command that saves the world, stops the Palworld
service, runs `steamcmd` to update/validate the dedicated server install, restarts the service, and
reports the outcome — replacing the current manual steamcmd workflow.

**Architecture:** A new `swee/server_update.py` module (mirroring the existing `swee/restart.py`)
owns the save→stop→steamcmd→start sequence and returns a result embed. `swee/commands.py` gets a
thin `/update` command that wires that function to a progress embed, exactly like the existing
`restart` command wires `restart_palworld`. Two new env vars (`PALWORLD_INSTALL_DIR`,
`STEAMCMD_PATH`) are added to `swee/config.py` and `.env.example`.

**Tech Stack:** Python 3.14, discord.py, asyncio subprocesses, no new dependencies.

## Global Constraints

- Palworld's Steam App ID is `2394010` — hardcoded, not configurable (spec: "Components §1").
- `PALWORLD_INSTALL_DIR` is required (no default); `STEAMCMD_PATH` defaults to
  `/usr/games/steamcmd` (spec: "Components §1").
- No sudoers changes — steamcmd runs as the same user the bot already runs as; only
  `systemctl stop`/`start` need sudo, reusing the existing `NOPASSWD` rule `/restart` relies on
  (spec: "Scope").
- The service is always restarted after the steamcmd step, regardless of whether steamcmd
  succeeded — never leave the server down (spec: "Components §3" error handling).
- No Discord-command test harness exists in this repo — this module is verified manually against
  the real server, not with automated tests (spec: "Testing"; `CLAUDE.md`).
- Reuse `restart_module._bot_restart_in_progress` around the stop/start so `log_tailer` treats the
  shutdown as planned (spec: "Components §3" step 2).

---

### Task 1: Config additions

**Files:**
- Modify: `swee/config.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `swee.config.PALWORLD_INSTALL_DIR` (str, required), `swee.config.STEAMCMD_PATH` (str,
  defaults to `"/usr/games/steamcmd"`) — consumed by Task 2.

- [ ] **Step 1: Add the two constants to `swee/config.py`**

Add immediately after the existing `PALWORLD_SERVICE_NAME` line (`swee/config.py:26`):

```python
PALWORLD_INSTALL_DIR = os.environ["PALWORLD_INSTALL_DIR"]
STEAMCMD_PATH = os.environ.get("STEAMCMD_PATH", "/usr/games/steamcmd")
```

- [ ] **Step 2: Document the vars in `.env.example`**

Add a new section after the existing "Palworld service" section (end of file):

```
# --- Palworld server update ---
# Absolute path steamcmd installs/updates the Palworld dedicated server into
# (passed as +force_install_dir). Must match the install used by PALWORLD_SERVICE_NAME.
PALWORLD_INSTALL_DIR=/home/steam/palworld/pal-chuds
# Path to the steamcmd binary. Defaults to /usr/games/steamcmd (apt install location) if unset.
# STEAMCMD_PATH=/usr/games/steamcmd
```

- [ ] **Step 3: Verify config loads**

Run: `python -c "import os; os.environ.setdefault('PALWORLD_INSTALL_DIR', '/tmp/x'); import swee.config as c; print(c.PALWORLD_INSTALL_DIR, c.STEAMCMD_PATH)"`

This will fail on the other required env vars (`GUILD_ID`, etc.) unless a real `.env` is present —
that's expected and fine; if it fails specifically on `PALWORLD_INSTALL_DIR` or `STEAMCMD_PATH`
being undefined, the new lines are wrong. If a `.env` already exists locally with the rest of the
vars filled in, add `PALWORLD_INSTALL_DIR=/tmp/x` to it temporarily and confirm the command prints
`/tmp/x /usr/games/steamcmd`, then remove the temporary line.

- [ ] **Step 4: Commit**

```bash
git add swee/config.py .env.example
git commit -m "feat: add config for Palworld server update via steamcmd"
```

---

### Task 2: `swee/server_update.py` module

**Files:**
- Create: `swee/server_update.py`

**Interfaces:**
- Consumes: `swee.config.PALWORLD_SERVICE_NAME`, `swee.config.PALWORLD_INSTALL_DIR`,
  `swee.config.STEAMCMD_PATH`, `swee.config.COLOR_READY`, `swee.config.COLOR_LEAVE` (all exist
  already except the two added in Task 1); `swee.rest_client.rest` (`.save()`, `.info()`);
  `swee.restart._bot_restart_in_progress` (module-level flag, read/write via
  `swee.restart` module reference, same pattern `swee/commands.py:88` uses).
- Produces: `async def update_palworld(on_progress=None) -> discord.Embed`, consumed by Task 3.
  `on_progress`, if given, is an `async def on_progress(status: str)` callable invoked at each
  stage transition (same contract as `restart_palworld`'s `on_progress` in `swee/restart.py:39`).

- [ ] **Step 1: Write the module**

```python
import asyncio
import logging
import time

import discord

import swee.restart as restart_module
from swee.config import COLOR_LEAVE, COLOR_READY, PALWORLD_INSTALL_DIR, PALWORLD_SERVICE_NAME, STEAMCMD_PATH
from swee.rest_client import rest

log = logging.getLogger("swee")

PALWORLD_STEAM_APP_ID = "2394010"


async def update_palworld(on_progress=None):
    if on_progress:
        await on_progress("Saving world…")
    try:
        await rest.save()
    except Exception:
        log.exception("server update: pre-update save failed")

    restart_module._bot_restart_in_progress = True
    try:
        if on_progress:
            await on_progress("Stopping server…")
        proc = await asyncio.create_subprocess_exec("sudo", "systemctl", "stop", PALWORLD_SERVICE_NAME)
        await proc.wait()

        if on_progress:
            await on_progress("Updating via steamcmd… this can take a few minutes")
        steamcmd_proc = await asyncio.create_subprocess_exec(
            STEAMCMD_PATH,
            "+force_install_dir", PALWORLD_INSTALL_DIR,
            "+login", "anonymous",
            "+app_update", PALWORLD_STEAM_APP_ID, "validate",
            "+quit",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await steamcmd_proc.communicate()
        steamcmd_ok = steamcmd_proc.returncode == 0
        steamcmd_output = stdout.decode(errors="replace").strip()

        if on_progress:
            await on_progress("Starting server…")
        start_proc = await asyncio.create_subprocess_exec("sudo", "systemctl", "start", PALWORLD_SERVICE_NAME)
        await start_proc.wait()

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
    finally:
        restart_module._bot_restart_in_progress = False

    if not steamcmd_ok:
        embed = discord.Embed(title="Update failed", color=COLOR_LEAVE)
        tail = steamcmd_output[-500:]
        if len(steamcmd_output) > 500:
            tail = "…" + tail
        embed.add_field(name="steamcmd output", value=f"```{tail}```" if tail else "(no output)", inline=False)
        embed.add_field(name="Status", value="Server was still restarted with the existing install.", inline=False)
        return embed

    if not online:
        embed = discord.Embed(title="Update timed out", color=COLOR_LEAVE)
        embed.add_field(
            name="Status",
            value=f"steamcmd succeeded but no response after {timeout}s — check `journalctl -u {PALWORLD_SERVICE_NAME}`",
        )
        return embed

    embed = discord.Embed(title="Server updated", color=COLOR_READY)
    embed.add_field(name="Status", value="steamcmd completed and the server is back online.")
    return embed
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `python -c "import swee.server_update"`

Expected: no import errors (this only exercises imports, not the async logic, since the module
has no test harness per the Global Constraints).

- [ ] **Step 3: Commit**

```bash
git add swee/server_update.py
git commit -m "feat: add update_palworld() to run steamcmd update via /update"
```

---

### Task 3: `/update` command

**Files:**
- Modify: `swee/commands.py`

**Interfaces:**
- Consumes: `update_palworld` from Task 2 (`from swee.server_update import update_palworld`).

- [ ] **Step 1: Add the import**

In `swee/commands.py`, alongside the existing `from swee.restart import restart_palworld`
(`swee/commands.py:13`), add:

```python
from swee.server_update import update_palworld
```

- [ ] **Step 2: Add the command**

Insert after the existing `restart` command (`swee/commands.py:74-93`), before the
`on_app_command_error` handler:

```python
@bot.tree.command(description="Update the Palworld server via steamcmd")
@is_admin()
async def update(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Updating Palworld server",
        color=COLOR_SHUTDOWN,
    )
    embed.add_field(name="Status", value="Saving world…")
    await interaction.response.send_message(embed=embed)

    async def on_progress(status):
        embed.set_field_at(0, name="Status", value=status)
        await interaction.edit_original_response(embed=embed)

    result_embed = await update_palworld(on_progress)
    await interaction.edit_original_response(embed=result_embed)
```

`COLOR_SHUTDOWN` is already imported at `swee/commands.py:9`.

- [ ] **Step 3: Verify it imports and registers cleanly**

Run: `python -c "import swee.commands"`

Expected: no import errors. (Full command registration requires a live bot connection, out of
reach for a manual `python -c` check — this only confirms there's no syntax/import mistake.)

- [ ] **Step 4: Commit**

```bash
git add swee/commands.py
git commit -m "feat: add /update admin command"
```

---

### Task 4: README documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a description of the update flow**

Add a new bullet after the existing "Config view/edit" bullet (`README.md:46-49`):

```markdown
- **Server update** — `/update` saves the world, stops the Palworld service, runs `steamcmd`
  against `PALWORLD_INSTALL_DIR` to update and validate the dedicated server install, then starts
  the service back up. The shutdown this causes is treated as planned (no "restarted
  unexpectedly" alert), and the existing "Server is online" log-tailer message reports the new
  version once it's back up. If `steamcmd` fails, the service is still restarted with the
  previously-installed files rather than left down.
```

- [ ] **Step 2: Add `update` to the admin-only command list**

In the "Running" section (`README.md:74`), change:

```
Slash commands are synced to `GUILD_ID` on startup. Admin-only commands (`save`, `kick`, `ban`,
`broadcast`, `restart`, `config list`, `config get`, `config set`) require `ADMIN_ROLE_ID`.
```

to:

```
Slash commands are synced to `GUILD_ID` on startup. Admin-only commands (`save`, `kick`, `ban`,
`broadcast`, `restart`, `update`, `config list`, `config get`, `config set`) require
`ADMIN_ROLE_ID`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document /update command"
```

---

### Task 5: Manual verification against the real server

**Files:** none (verification only, per the Global Constraints — no automated test harness for
this layer).

- [ ] **Step 1: Deploy the branch to the host and fill in the new env vars**

Set `PALWORLD_INSTALL_DIR` in `.env` to the real install path (e.g.
`/home/steam/palworld/pal-chuds`) and leave `STEAMCMD_PATH` unset if `/usr/games/steamcmd` is
correct on that host.

- [ ] **Step 2: Run `/update` and confirm the happy path**

Confirm: the progress embed cycles through "Saving world…" → "Stopping server…" → "Updating via
steamcmd…" → "Starting server…", the final embed is "Server updated", the server is reachable
in-game afterward, and `ALERTS_CHANNEL_ID` receives the existing "Server is online" message (not
"restarted unexpectedly").

- [ ] **Step 3: Confirm failure handling**

Temporarily set `PALWORLD_INSTALL_DIR` to a path steamcmd can't write to (or an invalid path),
run `/update` again, and confirm the result embed is "Update failed" with steamcmd's error output
visible, and that the server still comes back online afterward. Restore the correct
`PALWORLD_INSTALL_DIR` value afterward.

- [ ] **Step 4: Note results**

No commit for this task — it's verification only. If either check fails, return to Task 2 and fix
`swee/server_update.py` before considering the feature done.
