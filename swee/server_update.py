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
