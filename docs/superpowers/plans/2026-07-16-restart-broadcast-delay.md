# Restart/Update Warn-and-Delay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/restart` and `/update` broadcast an in-game + Discord warning and wait
`RAM_RESTART_WARNING_SEC` before restarting/stopping the Palworld server, matching the existing
RAM auto-restart behavior.

**Architecture:** Extract the broadcast+announce+sleep sequence already used by
`auto_restart_sequence` into a shared `warn_and_wait()` coroutine in `swee/restart.py`. Call it
from the `/restart` command handler (`swee/commands.py`) before restarting, and from the top of
`update_palworld()` (`swee/server_update.py`) before saving/stopping. No new config.

**Tech Stack:** Python 3.14, discord.py, existing `swee/` module structure.

## Global Constraints

- Reuse `RAM_RESTART_WARNING_SEC` (float, default 60s, from `swee/config.py`) as the delay for
  all three restart paths — no new env var.
- No automated test harness exists for the Discord command/async layer (see `CLAUDE.md`) — verify
  those paths manually against a running bot. `tests/` only covers `swee/palworld_settings.py`.
- Follow existing code patterns: `_bot_restart_in_progress` is set `True` only immediately before
  the actual stop/restart call, never during the warning/broadcast phase (this is how
  `auto_restart_sequence` already behaves — don't change that timing).

---

### Task 1: Extract `warn_and_wait()` helper and refactor `auto_restart_sequence`

**Files:**
- Modify: `swee/restart.py`

**Interfaces:**
- Produces: `async def warn_and_wait(discord_title: str, discord_description: str, ingame_message: str) -> None` — posts an embed to `ALERTS_CHANNEL_ID`, sends `rest.announce(ingame_message)` (logging and continuing on failure), then `asyncio.sleep(RAM_RESTART_WARNING_SEC)`.

- [ ] **Step 1: Replace the inline warn/announce/sleep block in `auto_restart_sequence` with a new `warn_and_wait` helper**

Edit `swee/restart.py`. Replace lines 72-86 (the `async def auto_restart_sequence(pct):` warning
block) so the file reads:

```python
async def warn_and_wait(discord_title, discord_description, ingame_message):
    warning_sec = int(RAM_RESTART_WARNING_SEC)
    await broadcast_embed(
        discord_title,
        discord_description,
        COLOR_SHUTDOWN,
        channel_id=ALERTS_CHANNEL_ID,
    )
    try:
        await rest.announce(ingame_message)
    except Exception:
        log.exception("in-game restart announce failed")
    await asyncio.sleep(warning_sec)


async def auto_restart_sequence(pct):
    global _bot_restart_in_progress
    warning_sec = int(RAM_RESTART_WARNING_SEC)
    await warn_and_wait(
        "High RAM usage detected",
        f"RAM usage at {pct}% — restarting server in {warning_sec}s.",
        f"Server restarting in {warning_sec}s due to high memory usage",
    )

    _bot_restart_in_progress = True
    try:
        embed = await restart_palworld()
    finally:
        _bot_restart_in_progress = False

    channel = bot.get_channel(ALERTS_CHANNEL_ID)
    if isinstance(channel, discord.TextChannel):
        await channel.send(embed=embed)
    else:
        log.warning("auto-restart result broadcast failed: channel %s not found or not a text channel", ALERTS_CHANNEL_ID)
```

The rest of the file (`check_palworld_service`, `restart_palworld`, `_log_auto_restart_failure`,
and the module-level `_bot_restart_in_progress` / imports) is unchanged.

- [ ] **Step 2: Sanity-check the module imports and compiles**

Run: `python -m py_compile swee/restart.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Manually confirm auto-restart wording is unchanged**

Re-read the new `auto_restart_sequence` against the original (git diff) — the Discord embed title
`"High RAM usage detected"`, description, in-game message text, and channel (`ALERTS_CHANNEL_ID`)
must be byte-for-byte identical to before the refactor. Run:

```bash
git diff swee/restart.py
```

Confirm the only behavioral change is the extraction into `warn_and_wait` — no wording or
sequencing differences in `auto_restart_sequence` itself.

- [ ] **Step 4: Commit**

```bash
git add swee/restart.py
git commit -m "refactor: extract warn_and_wait helper from auto_restart_sequence"
```

---

### Task 2: Wire warn-and-delay into `/restart`

**Files:**
- Modify: `swee/commands.py`

**Interfaces:**
- Consumes: `warn_and_wait(discord_title, discord_description, ingame_message)` from Task 1 (`swee/restart.py`); `RAM_RESTART_WARNING_SEC` from `swee/config.py`.

- [ ] **Step 1: Import `warn_and_wait` and `RAM_RESTART_WARNING_SEC`**

Edit `swee/commands.py` lines 8-14. Change:

```python
from swee.bot import bot, in_commands_channel, is_admin
from swee.config import COLOR_CHAT, COLOR_SHUTDOWN, OFFLINE_PLAYERS_LIMIT
from swee.embeds import add_status_fields, format_offline_field, format_online_field, offline_entries_from_history
from swee.player_history import online_players, player_history, refresh_online_players, session_started
from swee.rest_client import rest
from swee.restart import restart_palworld
from swee.server_update import update_palworld
```

to:

```python
from swee.bot import bot, in_commands_channel, is_admin
from swee.config import COLOR_CHAT, COLOR_SHUTDOWN, OFFLINE_PLAYERS_LIMIT, RAM_RESTART_WARNING_SEC
from swee.embeds import add_status_fields, format_offline_field, format_online_field, offline_entries_from_history
from swee.player_history import online_players, player_history, refresh_online_players, session_started
from swee.rest_client import rest
from swee.restart import restart_palworld, warn_and_wait
from swee.server_update import update_palworld
```

- [ ] **Step 2: Add the warning/delay step to the `/restart` command**

Edit `swee/commands.py` lines 75-94 (the `restart` command). Replace:

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

    restart_module._bot_restart_in_progress = True
    try:
        result_embed = await restart_palworld(on_progress)
    finally:
        restart_module._bot_restart_in_progress = False
    await interaction.edit_original_response(embed=result_embed)
```

with:

```python
@bot.tree.command(description="Restart the Palworld service")
@is_admin()
async def restart(interaction: discord.Interaction):
    warning_sec = int(RAM_RESTART_WARNING_SEC)
    embed = discord.Embed(
        title="Restarting Palworld server",
        color=COLOR_SHUTDOWN,
    )
    embed.add_field(name="Status", value="Broadcasting restart warning…")
    await interaction.response.send_message(embed=embed)

    await warn_and_wait(
        "Restarting server",
        f"Restarting server in {warning_sec}s (requested by admin).",
        f"Server restarting in {warning_sec}s",
    )

    embed.set_field_at(0, name="Status", value="Sending restart command…")
    await interaction.edit_original_response(embed=embed)

    async def on_progress(status):
        embed.set_field_at(0, name="Status", value=status)
        await interaction.edit_original_response(embed=embed)

    restart_module._bot_restart_in_progress = True
    try:
        result_embed = await restart_palworld(on_progress)
    finally:
        restart_module._bot_restart_in_progress = False
    await interaction.edit_original_response(embed=result_embed)
```

- [ ] **Step 3: Sanity-check imports and compile**

Run: `python -m py_compile swee/commands.py`
Expected: no output, exit code 0.

- [ ] **Step 4: Manual verification against a running bot**

This requires a live Discord bot connected to a Palworld server (per `CLAUDE.md`, this command
layer has no automated test harness). Steps:

1. Start the bot against a test/dev Palworld server (`python main.py`, or however you normally
   run it locally per `README.md`).
2. Run `/restart` from an admin-permitted channel.
3. Confirm: the command's response embed shows "Broadcasting restart warning…" immediately.
4. Confirm: within a second or two, `ALERTS_CHANNEL_ID` receives a new embed titled
   "Restarting server" with the description `"Restarting server in 60s (requested by admin)."`
   (or your configured `RAM_RESTART_WARNING_SEC`).
5. Confirm: an in-game chat/announce message reading `"Server restarting in 60s"` appears (check
   via the game client or `journalctl -u <service> -f`).
6. Confirm: the command's embed does **not** change to "Sending restart command…" until
   `RAM_RESTART_WARNING_SEC` has elapsed.
7. Confirm: the server actually restarts and the command's embed resolves to "Server restarted".

- [ ] **Step 5: Commit**

```bash
git add swee/commands.py
git commit -m "feat: broadcast in-game warning and delay before /restart"
```

---

### Task 3: Wire warn-and-delay into `/update`

**Files:**
- Modify: `swee/server_update.py`
- Modify: `swee/commands.py`

**Interfaces:**
- Consumes: `warn_and_wait(discord_title, discord_description, ingame_message)` from Task 1 (`swee/restart.py`); `RAM_RESTART_WARNING_SEC` from `swee/config.py`.

- [ ] **Step 1: Call `warn_and_wait` at the top of `update_palworld`**

Edit `swee/server_update.py`. Add the import and insert the warning call as the first action in
`update_palworld`. Change lines 1-18 from:

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
```

to:

```python
import asyncio
import logging
import time

import discord

import swee.restart as restart_module
from swee.config import COLOR_LEAVE, COLOR_READY, PALWORLD_INSTALL_DIR, PALWORLD_SERVICE_NAME, RAM_RESTART_WARNING_SEC, STEAMCMD_PATH
from swee.rest_client import rest
from swee.restart import warn_and_wait

log = logging.getLogger("swee")

PALWORLD_STEAM_APP_ID = "2394010"


async def update_palworld(on_progress=None):
    warning_sec = int(RAM_RESTART_WARNING_SEC)
    if on_progress:
        await on_progress("Broadcasting update warning…")
    await warn_and_wait(
        "Updating server",
        f"Updating server — restarting in {warning_sec}s for an update.",
        f"Server restarting in {warning_sec}s for an update",
    )

    if on_progress:
        await on_progress("Saving world…")
    try:
        await rest.save()
```

- [ ] **Step 2: Update the `/update` command's initial embed to match the new first progress step**

Edit `swee/commands.py` lines 97-105 (the `update` command). Change:

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
```

to:

```python
@bot.tree.command(description="Update the Palworld server via steamcmd")
@is_admin()
async def update(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Updating Palworld server",
        color=COLOR_SHUTDOWN,
    )
    embed.add_field(name="Status", value="Broadcasting update warning…")
    await interaction.response.send_message(embed=embed)
```

The rest of the `update` command (`on_progress` closure and the `update_palworld(on_progress)`
call) is unchanged — `update_palworld`'s new first `on_progress("Broadcasting update warning…")`
call is now redundant with the initial embed value but harmless (it re-sets the same text before
`warn_and_wait` starts).

- [ ] **Step 3: Sanity-check imports and compile**

Run: `python -m py_compile swee/server_update.py swee/commands.py`
Expected: no output, exit code 0.

- [ ] **Step 4: Manual verification against a running bot**

Same caveat as Task 2 — no automated harness for this layer. Steps:

1. With the bot running against a test/dev Palworld server, run `/update` from an admin-permitted
   channel.
2. Confirm: the response embed shows "Broadcasting update warning…" immediately.
3. Confirm: `ALERTS_CHANNEL_ID` receives an embed titled "Updating server" with description
   `"Updating server — restarting in 60s for an update."` (or configured value).
4. Confirm: an in-game announce reading `"Server restarting in 60s for an update"` appears.
5. Confirm: the response embed does not advance to "Saving world…" until
   `RAM_RESTART_WARNING_SEC` has elapsed.
6. Confirm: the rest of the update flow (save → stop → steamcmd → start) proceeds and completes
   as before.

- [ ] **Step 5: Commit**

```bash
git add swee/server_update.py swee/commands.py
git commit -m "feat: broadcast in-game warning and delay before /update"
```

---

### Task 4: Update `.env.example` documentation

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Broaden the `RAM_RESTART_WARNING_SEC` comment to cover all three restart paths**

Find the line in `.env.example`:

```
# RAM_RESTART_WARNING_SEC=60
```

Check the surrounding comment block (a few lines above it) describing what this variable does,
and update its wording so it no longer implies RAM-auto-restart-only scope. Replace the
comment immediately above `# RAM_RESTART_WARNING_SEC=60` with:

```
# Seconds to broadcast an in-game + Discord warning before restarting the server — used by
# the RAM auto-restart, and by /restart and /update.
# RAM_RESTART_WARNING_SEC=60
```

- [ ] **Step 2: Confirm the file still parses as valid env-style comments**

Run: `grep -n "RAM_RESTART_WARNING_SEC" .env.example`
Expected: shows the updated comment line and the `# RAM_RESTART_WARNING_SEC=60` line.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: broaden RAM_RESTART_WARNING_SEC comment to cover /restart and /update"
```

---

## Final Verification

- [ ] Run `python -m py_compile swee/restart.py swee/commands.py swee/server_update.py` — expect
  no output, exit code 0.
- [ ] Run `python -m unittest discover tests -v` — expect the existing `palworld_settings` tests
  to still pass (this change doesn't touch that module, so this just guards against import
  breakage across the package).
- [ ] Manually re-run the `/restart` and `/update` verification steps from Tasks 2 and 3 end to
  end against a real bot instance before opening a PR.
- [ ] Open a PR per `CLAUDE.md` (never push directly to `main`).
