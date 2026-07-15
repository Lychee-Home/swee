import logging
from datetime import datetime, timezone

import discord

from swee.bot import bot
from swee.config import ACTIVITY_CHANNEL_ID, COLOR_READY, OFFLINE_PLAYERS_LIMIT
from swee.player_history import session_started
from swee.ram import get_ram_usage

log = logging.getLogger("swee")


async def broadcast_embed(title, description, color, dt=None, channel_id=ACTIVITY_CHANNEL_ID, fields=None, fields_inline=True):
    embed = discord.Embed(title=title, description=description, color=color)
    if dt:
        embed.timestamp = dt
    for name, value in fields or []:
        embed.add_field(name=name, value=value, inline=fields_inline)
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        log.warning("broadcast failed: channel %s not found or not a text channel", channel_id)
        return None
    try:
        return await channel.send(embed=embed)
    except Exception:
        log.exception("broadcast failed")
        return None


def format_online_field(players, session_started):
    if not players:
        return "No one online."
    lines = []
    for p in players:
        joined_iso = session_started.get(p["name"])
        if joined_iso:
            ts = int(datetime.fromisoformat(joined_iso).timestamp())
            when = f"<t:{ts}:R>"
        else:
            when = "just now"
        lines.append(f"**{p['name']}** — Lv.{p['level']} — {when}")
    return "\n".join(lines)


def format_offline_field(entries, limit):
    if not entries:
        return "None yet."
    lines = [f"**{name}** — <t:{ts}:R>" for name, ts in entries[:limit]]
    if len(entries) > limit:
        lines.append(f"…and {len(entries) - limit} more")
    return "\n".join(lines)


def offline_entries_from_history(history, online_ids):
    entries = []
    for uid, rec in history.items():
        if uid in online_ids:
            continue
        dt = datetime.fromisoformat(rec["last_seen"])
        entries.append((rec["name"], int(dt.timestamp())))
    entries.sort(key=lambda e: e[1], reverse=True)
    return entries


def add_status_fields(embed, info, metrics, players, offline_entries):
    embed.add_field(name="Online", value=format_online_field(players, session_started), inline=False)
    embed.add_field(name="Offline", value=format_offline_field(offline_entries, OFFLINE_PLAYERS_LIMIT), inline=False)
    embed.add_field(name="FPS", value=metrics["serverfps"])
    embed.add_field(name="Uptime", value=f"{metrics['uptime'] // 3600}h")
    embed.add_field(name="Version", value=info["version"])
    return embed


def build_stats_embed(info, metrics, players, offline_entries):
    embed = discord.Embed(title=info["servername"], color=COLOR_READY)
    add_status_fields(embed, info, metrics, players, offline_entries)
    try:
        embed.add_field(name="System RAM", value=get_ram_usage())
    except Exception:
        log.exception("RAM read failed")
    embed.timestamp = datetime.now(timezone.utc)
    embed.set_footer(text="Last updated")
    return embed
