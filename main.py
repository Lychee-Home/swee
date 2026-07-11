import os
import re
import json
import time
import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
import httpx
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("swee")

GUILD_ID            = int(os.environ["GUILD_ID"])
RELAY_CHANNEL_ID    = int(os.environ["RELAY_CHANNEL_ID"]) if os.environ.get("RELAY_CHANNEL_ID") else None
STATS_CHANNEL_ID    = int(os.environ["STATS_CHANNEL_ID"])
ADMIN_ROLE_ID       = int(os.environ["ADMIN_ROLE_ID"])
ADMIN_CHANNEL_ID    = int(os.environ["ADMIN_CHANNEL_ID"])
COMMANDS_CHANNEL_ID = int(os.environ["COMMANDS_CHANNEL_ID"])
BOT_TOKEN           = os.environ["DISCORD_BOT_TOKEN"]

REST_BASE = f"http://{os.environ['REST_HOST']}:{os.environ['REST_PORT']}/v1/api"
REST_AUTH = httpx.BasicAuth(os.environ["REST_USER"], os.environ["REST_PASSWORD"])

ACTIVITY_CHANNEL_ID = int(os.environ["ACTIVITY_CHANNEL_ID"])
ALERTS_CHANNEL_ID   = int(os.environ["ALERTS_CHANNEL_ID"])
BOT_UPDATES_CHANNEL_ID = int(os.environ["BOT_UPDATES_CHANNEL_ID"])
GITHUB_REPO            = os.environ["GITHUB_REPO"]
PALWORLD_SETTINGS_INI_PATH = os.environ["PALWORLD_SETTINGS_INI_PATH"]

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
UPGRADE_LOG_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO Packages that will be upgraded: (.+)$'
)
RELEASE_NOTE_RE = re.compile(
    r'^\*\s*(?P<type>\w+)(\([^)]*\))?!?:\s*(?P<desc>.+?)\s+by\s+@\S+\s+in\s+\S+$'
)
RELEASE_NOTE_LABELS = {"feat": "🆕 New", "fix": "🛠️ Fixes", "perf": "🛠️ Fixes"}
# Section display order, derived from RELEASE_NOTE_LABELS itself (first-appearance order,
# de-duplicated) so the two never drift apart.
RELEASE_NOTE_SECTION_ORDER = tuple(dict.fromkeys(RELEASE_NOTE_LABELS.values()))
OPTION_SETTINGS_RE = re.compile(r'OptionSettings=\((.*)\)\s*$')

COLOR_CHAT, COLOR_JOIN, COLOR_LEAVE = 0x5865F2, 0x57F287, 0xED4245
COLOR_SHUTDOWN, COLOR_READY = 0xFEE75C, 0x57F287


# ---------- PalWorldSettings.ini parsing ----------
def _parse_option_settings(text):
    """Split the inner content of OptionSettings=(...) into a {key: value} dict.

    Values are either bare tokens (numbers, enum names, True/False) or double-quoted
    strings that may contain commas (e.g. ServerDescription="Hello, world") — a plain
    comma-split would break on those, so this scans char-by-char instead.
    """
    pairs = {}
    i, n = 0, len(text)
    while i < n:
        eq = text.index('=', i)
        key = text[i:eq]
        i = eq + 1
        if i < n and text[i] == '"':
            end = text.index('"', i + 1)
            value = text[i:end + 1]
            i = end + 1
            if i < n and text[i] == ',':
                i += 1
        else:
            comma = text.find(',', i)
            if comma == -1:
                value = text[i:]
                i = n
            else:
                value = text[i:comma]
                i = comma + 1
        pairs[key] = value
    return pairs


def parse_palworld_settings(path):
    with open(path) as f:
        content = f.read()
    m = OPTION_SETTINGS_RE.search(content)
    if not m:
        raise ValueError(f"no OptionSettings line found in {path}")
    return _parse_option_settings(m.group(1))


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


async def fetch_latest_release():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        return r.json()


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


async def broadcast_embed(title, description, color, dt=None, channel_id=ACTIVITY_CHANNEL_ID, fields=None):
    embed = discord.Embed(title=title, description=description, color=color)
    if dt:
        embed.timestamp = dt
    for name, value in fields or []:
        embed.add_field(name=name, value=value)
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        log.warning("broadcast failed: channel %s not found or not a text channel", channel_id)
        return None
    try:
        return await channel.send(embed=embed)
    except Exception:
        log.exception("broadcast failed")
        return None


# ---------- Live stats embed (separate channel, pinned, edited in place) ----------
stats_message_id = None  # cached once created, so we edit rather than re-send
_stats_lock = asyncio.Lock()  # serializes concurrent callers (ticker + join/leave events)
_last_auto_restart = None  # time.monotonic() of the last auto-restart trigger, or None
_auto_restart_task = None  # keeps a strong reference so asyncio doesn't GC it mid-run
_bot_restart_in_progress = False  # true while a bot-initiated restart (/restart or auto) is in flight

# ---------- Player history (online/offline tracking) ----------
PLAYER_HISTORY_PATH = "player_history.json"
player_history = {}   # userId -> {"name": str, "last_seen": ISO8601 str}
online_players = {}   # display name -> userId, refreshed on join/leave/tick
session_started = {}  # display name -> ISO8601 join timestamp, cleared on leave (not persisted)
# Safe without _stats_lock only because these dicts are never mutated across an `await`
# (asyncio is single-threaded); if that changes, guard the mutation with _stats_lock.

# ---------- Last release state (release announcement tracking) ----------
LAST_RELEASE_PATH = "last_release.json"
last_release_tag = None  # cached in-memory; mirrors last_release.json on disk


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


def load_last_release():
    global last_release_tag
    try:
        with open(LAST_RELEASE_PATH) as f:
            last_release_tag = json.load(f).get("tag")
    except FileNotFoundError:
        last_release_tag = None
    except json.JSONDecodeError:
        log.warning("last_release.json is corrupt, starting with no cached tag")
        last_release_tag = None


def save_last_release(tag):
    global last_release_tag
    last_release_tag = tag
    with open(LAST_RELEASE_PATH, "w") as f:
        json.dump({"tag": tag}, f, indent=2)


# ---------- Last Palworld settings snapshot (settings-change alert) ----------
PALWORLD_SETTINGS_CACHE_PATH = "last_palworld_settings.json"
last_palworld_settings = None  # cached in-memory; mirrors last_palworld_settings.json on disk; None until first check


def load_last_palworld_settings():
    global last_palworld_settings
    try:
        with open(PALWORLD_SETTINGS_CACHE_PATH) as f:
            last_palworld_settings = json.load(f)
    except FileNotFoundError:
        last_palworld_settings = None
    except json.JSONDecodeError:
        log.warning("last_palworld_settings.json is corrupt, starting with no cached settings")
        last_palworld_settings = None


def save_last_palworld_settings(settings):
    global last_palworld_settings
    last_palworld_settings = settings
    with open(PALWORLD_SETTINGS_CACHE_PATH, "w") as f:
        json.dump(settings, f, indent=2)


REDACTED_SETTINGS_KEYS = {"AdminPassword", "ServerPassword"}


def diff_palworld_settings(old, new):
    changes = []
    for key in sorted(set(old) | set(new)):
        old_val, new_val = old.get(key), new.get(key)
        if old_val != new_val:
            changes.append((key, old_val, new_val))
    return changes


def format_settings_change_fields(changes):
    fields = []
    # If more than 25 changes, only show 24 to leave room for the summary field
    display_limit = 24 if len(changes) > 25 else len(changes)

    for key, old_val, new_val in changes[:display_limit]:
        if key in REDACTED_SETTINGS_KEYS:
            display = "(changed)"
        else:
            display = f"{old_val if old_val is not None else '—'} → {new_val if new_val is not None else '—'}"
        fields.append((key, display))
    if len(changes) > 25:
        fields.append(("…", f"+{len(changes) - 24} more changed (see server config)"))
    return fields


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
            session_started[name] = dt.isoformat()
            player_history[uid] = {"name": name, "last_seen": dt.isoformat()}
            player_history.pop(f"name:{name}", None)  # supersede any stale fallback-key entry
            save_player_history()
            return


async def record_leave(name, dt):
    uid = online_players.pop(name, None)
    session_started.pop(name, None)
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
    current_names = {p["name"] for p in players_list}
    for stale_name in set(session_started) - current_names:
        session_started.pop(stale_name, None)
    for p in players_list:
        uid = p["userId"]
        online_players[p["name"]] = uid
        session_started.setdefault(p["name"], now_iso)
        player_history[uid] = {"name": p["name"], "last_seen": now_iso}
        player_history.pop(f"name:{p['name']}", None)  # supersede any stale fallback-key entry
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


def humanize_release_notes(body):
    grouped = {}
    for line in body.splitlines():
        m = RELEASE_NOTE_RE.match(line.strip())
        if not m:
            continue
        label = RELEASE_NOTE_LABELS.get(m.group("type"))
        if not label:
            continue
        desc = m.group("desc").strip()
        if desc:
            desc = desc[0].upper() + desc[1:]
        grouped.setdefault(label, []).append(desc)

    if not grouped:
        return None

    sections = []
    for label in RELEASE_NOTE_SECTION_ORDER:
        if label in grouped:
            lines = "\n".join(f"• {d}" for d in grouped[label])
            sections.append(f"{label}\n{lines}")
    return "\n\n".join(sections)


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
    global _bot_restart_in_progress
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


@tasks.loop(minutes=5)
async def release_ticker():
    global last_release_tag
    try:
        release = await fetch_latest_release()
    except Exception:
        log.exception("release check failed")
        return

    tag = release.get("tag_name")
    if not tag:
        return

    if last_release_tag is None:
        # First run with no cached state — seed it without announcing, so
        # shipping this feature doesn't dump a changelog for a release that
        # already happened before the bot could track it.
        save_last_release(tag)
        return

    if tag == last_release_tag:
        return

    body = release.get("body") or ""
    notes = humanize_release_notes(body)
    if notes is None:
        notes = body or "No release notes."
        max_len = 4000
        if len(notes) > max_len:
            notes = notes[:max_len] + "…"
    sent = await broadcast_embed(
        f"\U0001f389 {tag} released",
        notes,
        COLOR_READY,
        channel_id=BOT_UPDATES_CHANNEL_ID,
    )
    if sent:
        save_last_release(tag)
    else:
        log.warning("release announcement failed for %s, will retry next tick", tag)


# ---------- Log tailing (same events the original relay.py already captures) ----------
_log_tailer_task = None  # keeps a strong reference so asyncio doesn't GC it mid-run


async def check_palworld_settings_change():
    global last_palworld_settings
    try:
        new_settings = await asyncio.to_thread(parse_palworld_settings, PALWORLD_SETTINGS_INI_PATH)
    except Exception:
        log.warning("failed to read/parse PalWorldSettings.ini, skipping settings-change check", exc_info=True)
        return

    try:
        if last_palworld_settings is None:
            # First-ever check — seed the baseline without announcing, so shipping this
            # feature doesn't dump every existing setting as "changed" on first deploy.
            save_last_palworld_settings(new_settings)
            return

        changes = diff_palworld_settings(last_palworld_settings, new_settings)
        if not changes:
            return

        sent = await broadcast_embed(
            "Palworld settings changed",
            None,
            COLOR_SHUTDOWN,
            channel_id=ALERTS_CHANNEL_ID,
            fields=format_settings_change_fields(changes),
        )
        if sent:
            save_last_palworld_settings(new_settings)
        else:
            log.warning("settings-change alert failed to post, will retry next restart")
    except Exception:
        log.exception("settings-change check failed after parsing PalWorldSettings.ini")


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
                    elif m := VERSION_RE.search(msg):
                        if not _bot_restart_in_progress:
                            await broadcast_embed("Server is online", f"Game version: `{m.group(1)}`", COLOR_READY, dt, channel_id=ALERTS_CHANNEL_ID)
                        await check_palworld_settings_change()
            log.warning("log tailer: journalctl stream ended, restarting in 5s")
        except Exception:
            log.exception("log tailer crashed, restarting in 5s")
        await asyncio.sleep(5)


# ---------- Unplanned-restart cause detection ----------
UNATTENDED_UPGRADES_LOG = "/var/log/unattended-upgrades/unattended-upgrades.log"


def _read_last_lines(path, n):
    with open(path) as f:
        return f.readlines()[-n:]


async def detect_unattended_upgrades(shutdown_dt):
    try:
        lines = await asyncio.to_thread(_read_last_lines, UNATTENDED_UPGRADES_LOG, 100)
    except OSError:
        return None

    for line in reversed(lines):
        m = UPGRADE_LOG_RE.match(line.strip())
        if not m:
            continue
        try:
            # unattended-upgrades logs in system local time; assumes the host runs in UTC
            # (true for this deployment) — if that changes, this comparison silently stops
            # matching and just degrades to "cause unknown" rather than erroring.
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        delta = (shutdown_dt.astimezone(timezone.utc) - ts).total_seconds()
        if -30 <= delta <= 120:
            return "A routine system update installed a security patch that caused a restart."
        return None  # most recent entry too far from the shutdown time — no match
    return None


CAUSE_DETECTORS: list[Callable[[datetime], Awaitable[str | None]]] = [
    detect_unattended_upgrades,
]


async def detect_unplanned_restart_cause(shutdown_dt):
    for detector in CAUSE_DETECTORS:
        try:
            result = await detector(shutdown_dt)
        except Exception:
            log.exception("cause detector %s failed", detector.__name__)
            continue
        if result:
            return result
    return None


# ---------- Discord -> game ----------
@bot.event
async def on_message(message):
    if RELAY_CHANNEL_ID is None or message.author.bot or message.channel.id != RELAY_CHANNEL_ID:
        return
    if message.type not in (discord.MessageType.default, discord.MessageType.reply):
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
    try:
        players_list = (await rest.players()).get("players", [])
        refresh_online_players(players_list)
    except Exception:
        log.exception("player history: failed to fetch players for /status")
        players_list = []
    offline_entries = offline_entries_from_history(player_history, set(online_players.values()))
    embed = discord.Embed(title=info["servername"], color=COLOR_CHAT)
    add_status_fields(embed, info, metrics, players_list, offline_entries)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(description="List online and offline players")
@in_commands_channel()
async def players(interaction: discord.Interaction):
    plist = (await rest.players()).get("players", [])
    refresh_online_players(plist)
    offline_entries = offline_entries_from_history(player_history, set(online_players.values()))
    embed = discord.Embed(title="Players", color=COLOR_CHAT)
    embed.add_field(name="Online", value=format_online_field(plist, session_started), inline=False)
    embed.add_field(name="Offline", value=format_offline_field(offline_entries, OFFLINE_PLAYERS_LIMIT), inline=False)
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

    global _bot_restart_in_progress
    _bot_restart_in_progress = True
    try:
        result_embed = await restart_palworld(on_progress)
    finally:
        _bot_restart_in_progress = False
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
    release_ticker.start()
    log.info("Logged in as %s", bot.user)


async def main():
    discord.utils.setup_logging()
    if not check_palworld_service():
        raise SystemExit(1)
    load_player_history()
    load_last_release()
    load_last_palworld_settings()
    async with bot:
        await bot.start(BOT_TOKEN)
        # bot.start() returns once the bot is closed (e.g. Ctrl+C) — clean up
        # the background task and REST client rather than leaving them dangling.
        stats_ticker.cancel()
        release_ticker.cancel()
        if _log_tailer_task:
            _log_tailer_task.cancel()
        await rest.client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
