import os
import re
import json
import time
import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
import httpx
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("swee")

GUILD_ID            = int(os.environ["GUILD_ID"])
RELAY_CHANNEL_ID    = int(os.environ["RELAY_CHANNEL_ID"])
STATS_CHANNEL_ID    = int(os.environ["STATS_CHANNEL_ID"])
ADMIN_ROLE_ID       = int(os.environ["ADMIN_ROLE_ID"])
ADMIN_CHANNEL_ID    = int(os.environ["ADMIN_CHANNEL_ID"])
COMMANDS_CHANNEL_ID = int(os.environ["COMMANDS_CHANNEL_ID"])
BOT_TOKEN           = os.environ["DISCORD_BOT_TOKEN"]

REST_BASE = f"http://{os.environ['REST_HOST']}:{os.environ['REST_PORT']}/v1/api"
REST_AUTH = httpx.BasicAuth(os.environ["REST_USER"], os.environ["REST_PASSWORD"])

ACTIVITY_CHANNEL_ID = int(os.environ["ACTIVITY_CHANNEL_ID"])
ALERTS_CHANNEL_ID   = int(os.environ["ALERTS_CHANNEL_ID"])

_ram_restart_threshold_env = os.environ.get("RAM_RESTART_THRESHOLD_PCT")
RAM_RESTART_THRESHOLD_PCT = float(_ram_restart_threshold_env) if _ram_restart_threshold_env else None
RAM_RESTART_COOLDOWN_MIN = float(os.environ.get("RAM_RESTART_COOLDOWN_MIN", "15"))
RAM_RESTART_WARNING_SEC = float(os.environ.get("RAM_RESTART_WARNING_SEC", "60"))

OFFLINE_PLAYERS_LIMIT = int(os.environ.get("OFFLINE_PLAYERS_LIMIT", "10"))

PACIFIC = ZoneInfo("America/Los_Angeles")

JOIN_RE     = re.compile(r'\[LOG\]\s*(.+?) joined the server')
LEAVE_RE    = re.compile(r'\[LOG\]\s*(.+?) left the server')
TS_RE       = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)')
SHUTDOWN_RE = re.compile(r'Shutdown handler: initialize\.')
VERSION_RE  = re.compile(r'Game version is (v[\d.]+)')

COLOR_CHAT, COLOR_JOIN, COLOR_LEAVE = 0x5865F2, 0x57F287, 0xED4245
COLOR_SHUTDOWN, COLOR_READY = 0xFEE75C, 0x57F287


# ---------- REST client ----------
class PalRestClient:
    def __init__(self):
        self.client = httpx.AsyncClient(auth=REST_AUTH, timeout=5.0)

    async def get(self, path):
        r = await self.client.get(f"{REST_BASE}/{path}")
        r.raise_for_status()
        return r.json()

    async def post(self, path, payload=None):
        r = await self.client.post(f"{REST_BASE}/{path}", json=payload or {})
        r.raise_for_status()
        return r.json() if r.content else {}

    async def info(self):     return await self.get("info")
    async def players(self):  return await self.get("players")
    async def metrics(self):  return await self.get("metrics")
    async def announce(self, message):    return await self.post("announce", {"message": message})
    async def save(self):                 return await self.post("save")
    async def kick(self, uid, message=""): return await self.post("kick", {"userid": uid, "message": message})
    async def ban(self, uid, message=""):  return await self.post("ban", {"userid": uid, "message": message})


rest = PalRestClient()


# ---------- Bot setup ----------
intents = discord.Intents.default()
intents.message_content = True  # must also be enabled in the Discord Developer Portal

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Admin commands can only be used in the server.", ephemeral=True)
            return False
        if interaction.channel_id != ADMIN_CHANNEL_ID:
            await interaction.response.send_message(f"Admin commands can only be used in <#{ADMIN_CHANNEL_ID}>.", ephemeral=True)
            return False
        role = discord.utils.get(interaction.user.roles, id=ADMIN_ROLE_ID)
        if role is None:
            await interaction.response.send_message("Admin role required.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


def in_commands_channel():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.channel_id != COMMANDS_CHANNEL_ID:
            await interaction.response.send_message(f"This command can only be used in <#{COMMANDS_CHANNEL_ID}>.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


async def broadcast_embed(title, description, color, dt=None, channel_id=ACTIVITY_CHANNEL_ID):
    embed = discord.Embed(title=title, description=description, color=color)
    if dt:
        embed.timestamp = dt
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        log.warning("broadcast failed: channel %s not found or not a text channel", channel_id)
        return
    try:
        await channel.send(embed=embed)
    except Exception:
        log.exception("broadcast failed")


# ---------- Live stats embed (separate channel, pinned, edited in place) ----------
stats_message_id = None  # cached once created, so we edit rather than re-send
_stats_lock = asyncio.Lock()  # serializes concurrent callers (ticker + join/leave events)
_last_auto_restart = None  # time.monotonic() of the last auto-restart trigger, or None
_auto_restart_task = None  # keeps a strong reference so asyncio doesn't GC it mid-run
_auto_restart_in_progress = False  # suppresses log_tailer's own "Server is online" during a sequence

# ---------- Player history (online/offline tracking) ----------
PLAYER_HISTORY_PATH = "player_history.json"
player_history = {}   # userId -> {"name": str, "last_seen": ISO8601 str}
online_players = {}   # display name -> userId, refreshed on join/leave/tick


def load_player_history():
    global player_history
    try:
        with open(PLAYER_HISTORY_PATH) as f:
            player_history = json.load(f)
    except FileNotFoundError:
        player_history = {}
    except json.JSONDecodeError:
        log.warning("player_history.json is corrupt, starting with empty history")
        player_history = {}


def save_player_history():
    with open(PLAYER_HISTORY_PATH, "w") as f:
        json.dump(player_history, f, indent=2)


async def record_join(name, dt):
    try:
        data = await rest.players()
    except Exception:
        log.exception("player history: failed to fetch players on join for %s", name)
        return
    for p in data.get("players", []):
        if p["name"] == name:
            uid = p["userId"]
            online_players[name] = uid
            player_history[uid] = {"name": name, "last_seen": dt.isoformat()}
            save_player_history()
            return


async def record_leave(name, dt):
    uid = online_players.pop(name, None)
    if uid is None:
        uid = next((k for k, v in player_history.items() if v["name"] == name), None)
    if uid is None:
        uid = f"name:{name}"
        log.warning("player history: no stable ID found for %s on leave, using fallback key", name)
    player_history[uid] = {"name": name, "last_seen": dt.isoformat()}
    save_player_history()


def refresh_online_players(players_list):
    online_players.clear()
    now_iso = datetime.now(timezone.utc).astimezone(PACIFIC).isoformat()
    for p in players_list:
        uid = p["userId"]
        online_players[p["name"]] = uid
        player_history[uid] = {"name": p["name"], "last_seen": now_iso}
    save_player_history()


def offline_entries_from_history(history, online_ids):
    entries = []
    for uid, rec in history.items():
        if uid in online_ids:
            continue
        dt = datetime.fromisoformat(rec["last_seen"])
        entries.append((rec["name"], int(dt.timestamp())))
    entries.sort(key=lambda e: e[1], reverse=True)
    return entries


def format_online_field(players):
    if not players:
        return "No one online."
    return "\n".join(f"**{p['name']}** — Lv.{p['level']} ({round(p['ping'])}ms)" for p in players)


def format_offline_field(entries, limit):
    if not entries:
        return "None yet."
    lines = [f"**{name}** — <t:{ts}:R>" for name, ts in entries[:limit]]
    if len(entries) > limit:
        lines.append(f"…and {len(entries) - limit} more")
    return "\n".join(lines)


def read_ram_stats():
    # Bot runs on the same box as the game server, so read system memory
    # directly rather than via Palworld's REST API (which doesn't expose it).
    meminfo = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, value = line.split(":", 1)
            meminfo[key] = int(value.strip().split()[0])  # kB
    total_kb = meminfo["MemTotal"]
    available_kb = meminfo["MemAvailable"]
    used_gb = (total_kb - available_kb) / 1_048_576
    total_gb = total_kb / 1_048_576
    pct = round((used_gb / total_gb) * 100)
    return used_gb, total_gb, pct


def get_ram_usage():
    used_gb, total_gb, pct = read_ram_stats()
    return f"{used_gb:.1f}/{total_gb:.1f} GB ({pct}%)"


def should_auto_restart(pct, threshold_pct, last_restart_monotonic, now_monotonic, cooldown_min):
    if threshold_pct is None:
        return False
    if pct < threshold_pct:
        return False
    if last_restart_monotonic is None:
        return True
    return now_monotonic - last_restart_monotonic >= cooldown_min * 60


def add_status_fields(embed, info, metrics):
    embed.add_field(name="Players", value=f"{metrics['currentplayernum']}/{metrics['maxplayernum']}")
    embed.add_field(name="FPS", value=metrics["serverfps"])
    embed.add_field(name="Uptime", value=f"{metrics['uptime'] // 3600}h")
    embed.add_field(name="Version", value=info["version"])
    return embed


def build_stats_embed(info, metrics):
    embed = discord.Embed(title=info["servername"], color=COLOR_READY)
    add_status_fields(embed, info, metrics)
    try:
        embed.add_field(name="System RAM", value=get_ram_usage())
    except Exception:
        log.exception("RAM read failed")
    embed.timestamp = datetime.now(timezone.utc)
    embed.set_footer(text="Last updated")
    return embed


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


async def auto_restart_sequence(pct):
    global _auto_restart_in_progress
    warning_sec = int(RAM_RESTART_WARNING_SEC)
    await broadcast_embed(
        "High RAM usage detected",
        f"RAM usage at {pct}% — restarting server in {warning_sec}s.",
        COLOR_SHUTDOWN,
        channel_id=ALERTS_CHANNEL_ID,
    )
    try:
        await rest.announce(f"Server restarting in {warning_sec}s due to high memory usage")
    except Exception:
        log.exception("in-game auto-restart announce failed")

    await asyncio.sleep(RAM_RESTART_WARNING_SEC)

    _auto_restart_in_progress = True
    try:
        embed = await restart_palworld()
    finally:
        _auto_restart_in_progress = False

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


@tasks.loop(minutes=1)
async def stats_ticker():
    # Periodic tick for FPS/uptime, since those don't have a discrete log event.
    # Join/leave events also trigger an immediate update — see log_tailer below.
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


# ---------- Log tailing (same events the original relay.py already captures) ----------
_log_tailer_task = None  # keeps a strong reference so asyncio doesn't GC it mid-run


async def log_tailer():
    # journalctl can exit on its own (log rotation, service hiccup, etc.); without
    # this loop a single exit would silently kill the relay for good.
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                "journalctl", "-u", "palworld", "-f", "-n", "0", "-o", "json", "--no-pager",
                stdout=asyncio.subprocess.PIPE,
            )
            assert proc.stdout is not None
            async for line in proc.stdout:
                line = line.decode().strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = entry.get("MESSAGE", "")
                if isinstance(msg, list):
                    msg = " ".join(str(m) for m in msg)
                if not isinstance(msg, str):
                    continue

                micros = int(entry.get("__REALTIME_TIMESTAMP", 0))
                dt = datetime.fromtimestamp(micros / 1_000_000, tz=timezone.utc).astimezone(PACIFIC)

                ts_match = TS_RE.match(msg)
                if ts_match:
                    _, rest_msg = ts_match.groups()
                    if m := JOIN_RE.search(rest_msg):
                        await broadcast_embed(f"{m.group(1)} joined the server", None, COLOR_JOIN, dt)
                        await record_join(m.group(1), dt)
                        await update_stats_message()
                    elif m := LEAVE_RE.search(rest_msg):
                        await broadcast_embed(f"{m.group(1)} left the server", None, COLOR_LEAVE, dt)
                        await record_leave(m.group(1), dt)
                        await update_stats_message()
                else:
                    if SHUTDOWN_RE.search(msg):
                        await broadcast_embed("Server shutting down", None, COLOR_SHUTDOWN, dt, channel_id=ALERTS_CHANNEL_ID)
                    elif m := VERSION_RE.search(msg):
                        if not _auto_restart_in_progress:
                            await broadcast_embed("Server is online", f"Game version: `{m.group(1)}`", COLOR_READY, dt, channel_id=ALERTS_CHANNEL_ID)
            log.warning("log tailer: journalctl stream ended, restarting in 5s")
        except Exception:
            log.exception("log tailer crashed, restarting in 5s")
        await asyncio.sleep(5)


# ---------- Discord -> game ----------
@bot.event
async def on_message(message):
    if message.author.bot or message.channel.id != RELAY_CHANNEL_ID:
        return
    try:
        await rest.announce(f"{message.author.display_name}: {message.content}")
    except Exception:
        log.exception("announce failed")


# ---------- Slash commands ----------
@bot.tree.command(description="Show server status")
@in_commands_channel()
async def status(interaction: discord.Interaction):
    info, metrics = await rest.info(), await rest.metrics()
    embed = discord.Embed(title=info["servername"], color=COLOR_CHAT)
    add_status_fields(embed, info, metrics)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(description="List online players")
@in_commands_channel()
async def players(interaction: discord.Interaction):
    data = await rest.players()
    plist = data.get("players", [])
    embed = discord.Embed(title="Online Players", color=COLOR_CHAT)
    if not plist:
        embed.description = "No one online."
    else:
        lines = [f"**{p['name']}** — Lv.{p['level']} ({round(p['ping'])}ms)" for p in plist]
        embed.description = "\n".join(lines)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Force-save the world")
@is_admin()
async def save(interaction: discord.Interaction):
    await rest.save()
    await interaction.response.send_message("World saved.")


@bot.tree.command(description="Kick a player by SteamID")
@is_admin()
async def kick(interaction: discord.Interaction, steamid: str, reason: str = ""):
    await rest.kick(steamid, reason)
    await interaction.response.send_message(f"Kicked `{steamid}`.")


@bot.tree.command(description="Ban a player by SteamID")
@is_admin()
async def ban(interaction: discord.Interaction, steamid: str, reason: str = ""):
    await rest.ban(steamid, reason)
    await interaction.response.send_message(f"Banned `{steamid}`.")


@bot.tree.command(description="Send an in-game announcement")
@is_admin()
async def broadcast(interaction: discord.Interaction, message: str):
    await rest.announce(message)
    await interaction.response.send_message("Sent.")


def check_palworld_service():
    load_state = subprocess.run(
        ["systemctl", "show", "-p", "LoadState", "--value", "palworld"],
        capture_output=True, text=True,
    ).stdout.strip()
    if load_state != "loaded":
        log.error("palworld.service not found (LoadState=%s) — check the unit is installed", load_state or "unknown")
        return False

    sudo_check = subprocess.run(
        ["sudo", "-n", "-l", "systemctl", "restart", "palworld"], capture_output=True,
    )
    if sudo_check.returncode != 0:
        log.error(
            "passwordless sudo for 'systemctl restart palworld' not configured for this user "
            "— /restart and RAM auto-restart will hang"
        )
        return False

    return True


async def restart_palworld(on_progress=None):
    proc = await asyncio.create_subprocess_exec("sudo", "systemctl", "restart", "palworld")
    await proc.wait()

    if on_progress:
        await on_progress("Waiting for server to come back online\u2026")

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
            value=f"No response after {timeout}s \u2014 check `journalctl -u palworld`",
        )
    return embed


@bot.tree.command(description="Restart the Palworld service")
@is_admin()
async def restart(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Restarting Palworld server",
        color=COLOR_SHUTDOWN,
    )
    embed.add_field(name="Status", value="Sending restart command\u2026")
    await interaction.response.send_message(embed=embed)

    async def on_progress(status):
        embed.set_field_at(0, name="Status", value=status)
        await interaction.edit_original_response(embed=embed)

    result_embed = await restart_palworld(on_progress)
    await interaction.edit_original_response(embed=result_embed)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        return  # predicate (is_admin/in_commands_channel) already sent its own response

    command_name = interaction.command.name if interaction.command else "?"
    log.exception("command error in /%s", command_name, exc_info=error)

    message = "Something went wrong talking to the server."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    global _log_tailer_task
    _log_tailer_task = asyncio.create_task(log_tailer())
    stats_ticker.start()
    log.info("Logged in as %s", bot.user)


async def main():
    discord.utils.setup_logging()
    if not check_palworld_service():
        raise SystemExit(1)
    async with bot:
        await bot.start(BOT_TOKEN)
        # bot.start() returns once the bot is closed (e.g. Ctrl+C) — clean up
        # the background task and REST client rather than leaving them dangling.
        stats_ticker.cancel()
        if _log_tailer_task:
            _log_tailer_task.cancel()
        await rest.client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
