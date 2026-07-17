import asyncio
import logging
import subprocess
import time

import discord

from swee.bot import bot
from swee.config import ALERTS_CHANNEL_ID, COLOR_LEAVE, COLOR_READY, COLOR_SHUTDOWN, PALWORLD_SERVICE_NAME, RAM_RESTART_WARNING_SEC
from swee.embeds import broadcast_embed
from swee.rest_client import rest

log = logging.getLogger("swee")

_bot_restart_in_progress = False  # true while a bot-initiated restart (/restart or auto) is in flight


def check_palworld_service():
    load_state = subprocess.run(
        ["systemctl", "show", "-p", "LoadState", "--value", PALWORLD_SERVICE_NAME],
        capture_output=True, text=True,
    ).stdout.strip()
    if load_state != "loaded":
        log.error("%s.service not found (LoadState=%s) — check the unit is installed", PALWORLD_SERVICE_NAME, load_state or "unknown")
        return False

    sudo_check = subprocess.run(
        ["sudo", "-n", "-l", "systemctl", "restart", PALWORLD_SERVICE_NAME], capture_output=True,
    )
    if sudo_check.returncode != 0:
        log.error(
            "passwordless sudo for 'systemctl restart %s' not configured for this user "
            "— /restart and RAM auto-restart will hang", PALWORLD_SERVICE_NAME
        )
        return False

    return True


async def restart_palworld(on_progress=None):
    proc = await asyncio.create_subprocess_exec("sudo", "systemctl", "restart", PALWORLD_SERVICE_NAME)
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
            value=f"No response after {timeout}s — check `journalctl -u {PALWORLD_SERVICE_NAME}`",
        )
    return embed


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


def _log_auto_restart_failure(task):
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("auto-restart sequence failed", exc_info=exc)
