import asyncio
import logging
import time

import discord
from discord.ext import tasks

from swee.bot import bot
from swee.config import RAM_RESTART_COOLDOWN_MIN, RAM_RESTART_THRESHOLD_PCT, STATS_CHANNEL_ID
from swee.embeds import build_stats_embed, offline_entries_from_history
from swee.player_history import online_players, player_history, refresh_online_players
from swee.ram import read_ram_stats, should_auto_restart
from swee.rest_client import rest
from swee.restart import _log_auto_restart_failure, auto_restart_sequence

log = logging.getLogger("swee")

stats_message_id = None  # cached once created, so we edit rather than re-send
_stats_lock = asyncio.Lock()  # serializes concurrent callers (ticker + join/leave events)
_last_auto_restart = None  # time.monotonic() of the last auto-restart trigger, or None
_auto_restart_task = None  # keeps a strong reference so asyncio doesn't GC it mid-run


async def update_stats_message():
    global stats_message_id
    channel = bot.get_channel(STATS_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        log.warning("stats update failed: channel %s not found or not a text channel", STATS_CHANNEL_ID)
        return
    # Only called after on_ready starts the ticker/log tailer, so bot.user is always set.
    assert bot.user is not None
    async with _stats_lock:
        try:
            info, metrics = await rest.info(), await rest.metrics()
            try:
                players_list = (await rest.players()).get("players", [])
                refresh_online_players(players_list)
            except Exception:
                log.exception("player history: failed to refresh online players")
                players_list = []
            offline_entries = offline_entries_from_history(player_history, set(online_players.values()))
            embed = build_stats_embed(info, metrics, players_list, offline_entries)

            if stats_message_id:
                try:
                    msg = await channel.fetch_message(stats_message_id)
                    await msg.edit(embed=embed)
                    return
                except discord.NotFound:
                    stats_message_id = None  # message was deleted, fall through and recreate

            # No cached ID (e.g. bot just restarted) — check pins for one we already made
            # before creating a new one, so restarts don't spawn duplicate messages.
            async for pinned in channel.pins():
                if pinned.author.id == bot.user.id:
                    await pinned.edit(embed=embed)
                    stats_message_id = pinned.id
                    return

            msg = await channel.send(embed=embed)
            await msg.pin()
            stats_message_id = msg.id
        except Exception:
            log.exception("stats message update failed")


@tasks.loop(minutes=1)
async def stats_ticker():
    # Periodic tick for FPS/uptime, since those don't have a discrete log event.
    # Join/leave events also trigger an immediate update — see swee.log_tailer.log_tailer.
    await update_stats_message()

    if RAM_RESTART_THRESHOLD_PCT is None:
        return

    global _last_auto_restart, _auto_restart_task
    try:
        _, _, pct = read_ram_stats()
    except Exception:
        log.exception("RAM read failed for auto-restart check")
        return

    now = time.monotonic()
    if should_auto_restart(pct, RAM_RESTART_THRESHOLD_PCT, _last_auto_restart, now, RAM_RESTART_COOLDOWN_MIN):
        _last_auto_restart = now
        _auto_restart_task = asyncio.create_task(auto_restart_sequence(pct))
        _auto_restart_task.add_done_callback(_log_auto_restart_failure)
