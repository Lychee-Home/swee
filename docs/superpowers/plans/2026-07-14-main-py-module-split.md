# Split main.py into a swee/ package — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 980-line `main.py` into a `swee/` package of single-responsibility modules with zero behavior change, keeping `main.py` at the repo root as a thin composition root (required by `deploy/swee.service`'s `ExecStart`).

**Architecture:** Thirteen new modules under `swee/`, ordered as a strict dependency chain (`config`/`bot` at the bottom, `main.py` at the top) so there are no circular imports. Two mechanical adjustments are required for correctness across the new module boundaries — see **Global Constraints**.

**Tech Stack:** Python 3.14, discord.py, httpx, python-dotenv (all unchanged — no new dependencies).

## Global Constraints

- **No behavior change.** Every function body is moved verbatim. Do not fix bugs, rename things beyond what the split requires, or restructure logic, even where it looks improvable.
- **`main.py` stays at the repo root** — `deploy/swee.service` runs `.../python .../main.py` directly.
- **Two required (not optional) adjustments** to keep shared mutable state correct across module boundaries — these are part of "the move," not cleanup:
  1. `player_history.py`'s `load_player_history()` must mutate the `player_history` dict **in place** (`.clear()` + `.update(...)`) instead of reassigning it with `=`. Reason: `stats.py` and `commands.py` import the `player_history` dict by name at module-load time (`from swee.player_history import player_history`); if `load_player_history()` reassigned it to a new dict object, those other modules would keep holding a reference to the old (empty) dict forever, silently breaking the offline-players feature. `online_players` and `session_started` are already safe as-is (the original code only ever mutates them in place, never reassigns).
  2. `_bot_restart_in_progress` lives in `restart.py` as a plain module attribute. `commands.py` and `log_tailer.py` must read/write it via a qualified module import (`import swee.restart as restart_module`, then `restart_module._bot_restart_in_progress`), **not** `from swee.restart import _bot_restart_in_progress`. Reason: it's a `bool`, reassigned with `global` inside `restart.py`; a `from`-import copies the reference at import time and would never see later updates.
  3. `_log_auto_restart_failure` moves into `restart.py` alongside `auto_restart_sequence` (its only caller-adjacent function) rather than `stats.py` — a small refinement over the design spec, made for the same "keep tightly-coupled things together" reason the spec already applies elsewhere. `stats.py` imports both by name (safe — they're functions, not reassigned variables).
- No test suite exists in this repo (per `CLAUDE.md`) — verification is via `python -m py_compile` per file (syntax only, no env vars needed) plus a final end-to-end import smoke test using a throwaway `.env` (Task 14).

---

### Task 1: Package skeleton + `config.py`

**Files:**
- Create: `swee/__init__.py`
- Create: `swee/config.py`

**Interfaces:**
- Produces: `GUILD_ID`, `RELAY_CHANNEL_ID`, `STATS_CHANNEL_ID`, `ADMIN_ROLE_ID`, `ADMIN_CHANNEL_ID`, `COMMANDS_CHANNEL_ID`, `BOT_TOKEN`, `REST_BASE`, `REST_AUTH`, `ACTIVITY_CHANNEL_ID`, `ALERTS_CHANNEL_ID`, `BOT_UPDATES_CHANNEL_ID`, `GITHUB_REPO`, `GITHUB_TOKEN`, `PALWORLD_SETTINGS_INI_PATH`, `PALWORLD_SERVICE_NAME`, `RAM_RESTART_THRESHOLD_PCT`, `RAM_RESTART_COOLDOWN_MIN`, `RAM_RESTART_WARNING_SEC`, `OFFLINE_PLAYERS_LIMIT`, `PACIFIC`, `COLOR_CHAT`, `COLOR_JOIN`, `COLOR_LEAVE`, `COLOR_SHUTDOWN`, `COLOR_READY` (all `str`/`int`/`float`/`None`/`ZoneInfo`/`httpx.BasicAuth` constants, unchanged values from current `main.py` lines 22-68).

- [ ] **Step 1: Create the empty package marker**

```python
# swee/__init__.py
```

(Empty file — just makes `swee/` an importable package.)

- [ ] **Step 2: Write `swee/config.py`**

```python
import os
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

load_dotenv()

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
GITHUB_TOKEN           = os.environ.get("GITHUB_TOKEN")
PALWORLD_SETTINGS_INI_PATH = os.environ["PALWORLD_SETTINGS_INI_PATH"]
PALWORLD_SERVICE_NAME = os.environ.get("PALWORLD_SERVICE_NAME", "palworld")

_ram_restart_threshold_env = os.environ.get("RAM_RESTART_THRESHOLD_PCT")
RAM_RESTART_THRESHOLD_PCT = float(_ram_restart_threshold_env) if _ram_restart_threshold_env else None
RAM_RESTART_COOLDOWN_MIN = float(os.environ.get("RAM_RESTART_COOLDOWN_MIN", "15"))
RAM_RESTART_WARNING_SEC = float(os.environ.get("RAM_RESTART_WARNING_SEC", "60"))

OFFLINE_PLAYERS_LIMIT = int(os.environ.get("OFFLINE_PLAYERS_LIMIT", "10"))

PACIFIC = ZoneInfo("America/Los_Angeles")

COLOR_CHAT, COLOR_JOIN, COLOR_LEAVE = 0x5865F2, 0x57F287, 0xED4245
COLOR_SHUTDOWN, COLOR_READY = 0xFEE75C, 0x57F287
```

- [ ] **Step 3: Syntax-check both files**

Run: `python -m py_compile swee/__init__.py swee/config.py`
Expected: no output, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add swee/__init__.py swee/config.py
git commit -m "refactor: extract config.py from main.py"
```

---

### Task 2: `bot.py`

**Files:**
- Create: `swee/bot.py`

**Interfaces:**
- Consumes: `swee.config.{ADMIN_CHANNEL_ID, ADMIN_ROLE_ID, COMMANDS_CHANNEL_ID}`
- Produces: `bot` (`commands.Bot` instance), `is_admin()` (decorator factory), `in_commands_channel()` (decorator factory)

- [ ] **Step 1: Write `swee/bot.py`**

```python
import discord
from discord import app_commands
from discord.ext import commands

from swee.config import ADMIN_CHANNEL_ID, ADMIN_ROLE_ID, COMMANDS_CHANNEL_ID

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
```

- [ ] **Step 2: Syntax-check**

Run: `python -m py_compile swee/bot.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add swee/bot.py
git commit -m "refactor: extract bot.py from main.py"
```

---

### Task 3: `rest_client.py`

**Files:**
- Create: `swee/rest_client.py`

**Interfaces:**
- Consumes: `swee.config.{REST_AUTH, REST_BASE}`
- Produces: `PalRestClient` class, `rest` singleton instance (with `.client`, `.info()`, `.players()`, `.metrics()`, `.announce(message)`, `.save()`, `.kick(uid, message="")`, `.ban(uid, message="")`)

- [ ] **Step 1: Write `swee/rest_client.py`**

```python
import httpx

from swee.config import REST_AUTH, REST_BASE


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
```

- [ ] **Step 2: Syntax-check**

Run: `python -m py_compile swee/rest_client.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add swee/rest_client.py
git commit -m "refactor: extract rest_client.py from main.py"
```

---

### Task 4: `palworld_settings.py`

**Files:**
- Create: `swee/palworld_settings.py`

**Interfaces:**
- Consumes: nothing (pure module — no `swee` imports)
- Produces: `OPTION_SETTINGS_RE`, `REDACTED_SETTINGS_KEYS`, `parse_palworld_settings(path)`, `diff_palworld_settings(old, new)`, `format_settings_change_fields(changes)`

- [ ] **Step 1: Write `swee/palworld_settings.py`**

```python
import re

OPTION_SETTINGS_RE = re.compile(r'OptionSettings=\((.*)\)\s*$')

REDACTED_SETTINGS_KEYS = {"AdminPassword", "ServerPassword"}


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
```

- [ ] **Step 2: Syntax-check**

Run: `python -m py_compile swee/palworld_settings.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add swee/palworld_settings.py
git commit -m "refactor: extract palworld_settings.py from main.py"
```

---

### Task 5: `ram.py`

**Files:**
- Create: `swee/ram.py`

**Interfaces:**
- Consumes: nothing (pure module — the RAM threshold is passed in by callers, not read from config here)
- Produces: `read_ram_stats()` → `(used_gb, total_gb, pct)`, `get_ram_usage()` → `str`, `should_auto_restart(pct, threshold_pct, last_restart_monotonic, now_monotonic, cooldown_min)` → `bool`

- [ ] **Step 1: Write `swee/ram.py`**

```python
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
```

- [ ] **Step 2: Syntax-check**

Run: `python -m py_compile swee/ram.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add swee/ram.py
git commit -m "refactor: extract ram.py from main.py"
```

---

### Task 6: `player_history.py`

**Files:**
- Create: `swee/player_history.py`

**Interfaces:**
- Consumes: `swee.config.PACIFIC`, `swee.rest_client.rest`
- Produces: `PLAYER_HISTORY_PATH`, `player_history` (dict, **mutated in place only** — see Global Constraints), `online_players` (dict), `session_started` (dict), `load_player_history()`, `save_player_history()`, `record_join(name, dt)` (async), `record_leave(name, dt)` (async), `refresh_online_players(players_list)`

- [ ] **Step 1: Write `swee/player_history.py`**

```python
import json
import logging
from datetime import datetime, timezone

from swee.config import PACIFIC
from swee.rest_client import rest

log = logging.getLogger("swee")

PLAYER_HISTORY_PATH = "player_history.json"
player_history = {}   # userId -> {"name": str, "last_seen": ISO8601 str}
online_players = {}   # display name -> userId, refreshed on join/leave/tick
session_started = {}  # display name -> ISO8601 join timestamp, cleared on leave (not persisted)
# Safe without a lock only because these dicts are never mutated across an `await`
# (asyncio is single-threaded); if that changes, guard the mutation with a lock.
#
# `player_history` is always mutated in place (.clear()/.update()/item assignment),
# never reassigned with `=` — other modules import this dict by name at load time
# (`from swee.player_history import player_history`), so reassigning it here would
# leave those modules holding a stale reference.


def load_player_history():
    player_history.clear()
    try:
        with open(PLAYER_HISTORY_PATH) as f:
            player_history.update(json.load(f))
    except FileNotFoundError:
        pass
    except json.JSONDecodeError:
        log.warning("player_history.json is corrupt, starting with empty history")


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
```

- [ ] **Step 2: Syntax-check**

Run: `python -m py_compile swee/player_history.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add swee/player_history.py
git commit -m "refactor: extract player_history.py from main.py"
```

---

### Task 7: `embeds.py`

**Files:**
- Create: `swee/embeds.py`

**Interfaces:**
- Consumes: `swee.bot.bot`, `swee.config.{ACTIVITY_CHANNEL_ID, COLOR_READY, OFFLINE_PLAYERS_LIMIT}`, `swee.player_history.session_started`, `swee.ram.get_ram_usage`
- Produces: `broadcast_embed(...)` (async), `format_online_field(players, session_started)`, `format_offline_field(entries, limit)`, `offline_entries_from_history(history, online_ids)`, `add_status_fields(embed, info, metrics, players, offline_entries)`, `build_stats_embed(info, metrics, players, offline_entries)`

- [ ] **Step 1: Write `swee/embeds.py`**

```python
import logging
from datetime import datetime, timezone

import discord

from swee.bot import bot
from swee.config import ACTIVITY_CHANNEL_ID, COLOR_READY, OFFLINE_PLAYERS_LIMIT
from swee.player_history import session_started
from swee.ram import get_ram_usage

log = logging.getLogger("swee")


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
```

- [ ] **Step 2: Syntax-check**

Run: `python -m py_compile swee/embeds.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add swee/embeds.py
git commit -m "refactor: extract embeds.py from main.py"
```

---

### Task 8: `releases.py`

**Files:**
- Create: `swee/releases.py`

**Interfaces:**
- Consumes: `swee.config.{BOT_UPDATES_CHANNEL_ID, COLOR_READY, GITHUB_REPO, GITHUB_TOKEN}`, `swee.embeds.broadcast_embed`
- Produces: `LAST_RELEASE_PATH`, `last_release_tag` (module-internal only — no other module reads/writes it), `load_last_release()`, `save_last_release(tag)`, `fetch_latest_release()` (async), `humanize_release_notes(body)`, `release_ticker` (`tasks.Loop`, 5 min)

- [ ] **Step 1: Write `swee/releases.py`**

```python
import json
import logging
import re

import httpx
from discord.ext import tasks

from swee.config import BOT_UPDATES_CHANNEL_ID, COLOR_READY, GITHUB_REPO, GITHUB_TOKEN
from swee.embeds import broadcast_embed

log = logging.getLogger("swee")

RELEASE_NOTE_RE = re.compile(
    r'^\*\s*(?P<type>\w+)(\([^)]*\))?!?:\s*(?P<desc>.+?)\s+by\s+@\S+\s+in\s+\S+$'
)
RELEASE_NOTE_LABELS = {"feat": "New", "fix": "Fixes", "perf": "Fixes"}
# Section display order, derived from RELEASE_NOTE_LABELS itself (first-appearance order,
# de-duplicated) so the two never drift apart.
RELEASE_NOTE_SECTION_ORDER = tuple(dict.fromkeys(RELEASE_NOTE_LABELS.values()))

LAST_RELEASE_PATH = "last_release.json"
last_release_tag = None  # cached in-memory; mirrors last_release.json on disk


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


async def fetch_latest_release():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


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
            sections.append(f"**{label}**\n{lines}")
    return "\n\n".join(sections)


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
        f"{tag} released",
        notes,
        COLOR_READY,
        channel_id=BOT_UPDATES_CHANNEL_ID,
    )
    if sent:
        save_last_release(tag)
    else:
        log.warning("release announcement failed for %s, will retry next tick", tag)
```

- [ ] **Step 2: Syntax-check**

Run: `python -m py_compile swee/releases.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add swee/releases.py
git commit -m "refactor: extract releases.py from main.py"
```

---

### Task 9: `restart.py`

**Files:**
- Create: `swee/restart.py`

**Interfaces:**
- Consumes: `swee.bot.bot`, `swee.config.{ALERTS_CHANNEL_ID, COLOR_LEAVE, COLOR_READY, COLOR_SHUTDOWN, PALWORLD_SERVICE_NAME, RAM_RESTART_WARNING_SEC}`, `swee.embeds.broadcast_embed`, `swee.rest_client.rest`
- Produces: `check_palworld_service()` → `bool`, `restart_palworld(on_progress=None)` (async) → `discord.Embed`, `auto_restart_sequence(pct)` (async), `_log_auto_restart_failure(task)`, `_bot_restart_in_progress` (module attribute — read/write only via `import swee.restart as restart_module` from other modules, per Global Constraints)

- [ ] **Step 1: Write `swee/restart.py`**

```python
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
```

- [ ] **Step 2: Syntax-check**

Run: `python -m py_compile swee/restart.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add swee/restart.py
git commit -m "refactor: extract restart.py from main.py"
```

---

### Task 10: `cause_detection.py`

**Files:**
- Create: `swee/cause_detection.py`

**Interfaces:**
- Consumes: `swee.config.{ALERTS_CHANNEL_ID, COLOR_SHUTDOWN, PALWORLD_SETTINGS_INI_PATH}`, `swee.embeds.broadcast_embed`, `swee.palworld_settings.{diff_palworld_settings, format_settings_change_fields, parse_palworld_settings}`
- Produces: `PALWORLD_SETTINGS_CACHE_PATH`, `last_palworld_settings` (module-internal only), `load_last_palworld_settings()`, `save_last_palworld_settings(settings)`, `check_palworld_settings_change()` (async), `UNATTENDED_UPGRADES_LOG`, `UPGRADE_LOG_RE`, `detect_unattended_upgrades(shutdown_dt)` (async), `detect_ini_settings_change(shutdown_dt)` (async), `CAUSE_DETECTORS` (list), `detect_unplanned_restart_cause(shutdown_dt)` (async) → `(str, dict | None) | None`

- [ ] **Step 1: Write `swee/cause_detection.py`**

```python
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable

from swee.config import ALERTS_CHANNEL_ID, COLOR_SHUTDOWN, PALWORLD_SETTINGS_INI_PATH
from swee.embeds import broadcast_embed
from swee.palworld_settings import diff_palworld_settings, format_settings_change_fields, parse_palworld_settings

log = logging.getLogger("swee")

# ---------- Palworld settings snapshot (settings-change alert + unplanned-restart cause) ----------
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


# ---------- Unplanned-restart cause detection ----------
UNATTENDED_UPGRADES_LOG = "/var/log/unattended-upgrades/unattended-upgrades.log"
UPGRADE_LOG_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO Packages that will be upgraded: (.+)$'
)


def _read_last_lines(path, n):
    with open(path) as f:
        return f.readlines()[-n:]


async def detect_unattended_upgrades(shutdown_dt):
    try:
        lines = await asyncio.to_thread(_read_last_lines, UNATTENDED_UPGRADES_LOG, 100)
    except FileNotFoundError:
        return None
    except OSError:
        log.warning("cause detector: cannot read %s", UNATTENDED_UPGRADES_LOG, exc_info=True)
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
            return "A routine system update installed a security patch that caused a restart.", None
        return None  # most recent entry too far from the shutdown time — no match
    return None


async def detect_ini_settings_change(shutdown_dt):
    try:
        new_settings = await asyncio.to_thread(parse_palworld_settings, PALWORLD_SETTINGS_INI_PATH)
    except Exception:
        log.warning("cause detector: failed to read/parse PalWorldSettings.ini", exc_info=True)
        return None

    if last_palworld_settings is None:
        return "Settings-change tracking just initialized — no prior baseline to compare against.", None

    changes = diff_palworld_settings(last_palworld_settings, new_settings)
    if not changes:
        return None

    lines = [f"**{k}**: {v}" for k, v in format_settings_change_fields(changes)]
    cause = "\n".join(lines)
    if len(cause) > 1024:  # Discord embed field value limit
        cause = cause[:1000] + "…"
    return cause, new_settings


CAUSE_DETECTORS: list[Callable[[datetime], Awaitable[tuple[str, dict | None] | None]]] = [
    detect_unattended_upgrades,
    detect_ini_settings_change,
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
```

- [ ] **Step 2: Syntax-check**

Run: `python -m py_compile swee/cause_detection.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add swee/cause_detection.py
git commit -m "refactor: extract cause_detection.py from main.py"
```

---

### Task 11: `stats.py`

**Files:**
- Create: `swee/stats.py`

**Interfaces:**
- Consumes: `swee.bot.bot`, `swee.config.{RAM_RESTART_COOLDOWN_MIN, RAM_RESTART_THRESHOLD_PCT, STATS_CHANNEL_ID}`, `swee.embeds.{build_stats_embed, offline_entries_from_history}`, `swee.player_history.{online_players, player_history, refresh_online_players}`, `swee.ram.{read_ram_stats, should_auto_restart}`, `swee.rest_client.rest`, `swee.restart.{_log_auto_restart_failure, auto_restart_sequence}`
- Produces: `update_stats_message()` (async), `stats_ticker` (`tasks.Loop`, 1 min)

Note: `stats.py` must be created *before* `log_tailer.py` (Task 12), which imports `update_stats_message` from it.

- [ ] **Step 1: Write `swee/stats.py`**

```python
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
```

- [ ] **Step 2: Syntax-check**

Run: `python -m py_compile swee/stats.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add swee/stats.py
git commit -m "refactor: extract stats.py from main.py"
```

---

### Task 12: `log_tailer.py`

**Files:**
- Create: `swee/log_tailer.py`

**Interfaces:**
- Consumes: `swee.cause_detection.{check_palworld_settings_change, detect_unplanned_restart_cause, save_last_palworld_settings}`, `swee.config.{ALERTS_CHANNEL_ID, COLOR_JOIN, COLOR_LEAVE, COLOR_READY, COLOR_SHUTDOWN, PACIFIC, PALWORLD_SERVICE_NAME}`, `swee.embeds.broadcast_embed`, `swee.player_history.{record_join, record_leave}`, `swee.stats.update_stats_message`, `swee.restart` (module, for `_bot_restart_in_progress`)
- Produces: `log_tailer()` (async, infinite loop)

- [ ] **Step 1: Write `swee/log_tailer.py`**

```python
import asyncio
import json
import logging
import re
from datetime import datetime, timezone

import swee.restart as restart_module
from swee.cause_detection import check_palworld_settings_change, detect_unplanned_restart_cause, save_last_palworld_settings
from swee.config import ALERTS_CHANNEL_ID, COLOR_JOIN, COLOR_LEAVE, COLOR_READY, COLOR_SHUTDOWN, PACIFIC, PALWORLD_SERVICE_NAME
from swee.embeds import broadcast_embed
from swee.player_history import record_join, record_leave
from swee.stats import update_stats_message

log = logging.getLogger("swee")

JOIN_RE     = re.compile(r'\[LOG\]\s*(.+?) joined the server')
LEAVE_RE    = re.compile(r'\[LOG\]\s*(.+?) left the server')
TS_RE       = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)')
SHUTDOWN_RE = re.compile(r'Shutdown handler: initialize\.')
VERSION_RE  = re.compile(r'Game version is (v[\d.]+)')


async def log_tailer():
    # journalctl can exit on its own (log rotation, service hiccup, etc.); without
    # this loop a single exit would silently kill the relay for good.
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                "journalctl", "-u", PALWORLD_SERVICE_NAME, "-f", "-n", "0", "-o", "json", "--no-pager",
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
                        if restart_module._bot_restart_in_progress:
                            await broadcast_embed("Server shutting down", None, COLOR_SHUTDOWN, dt, channel_id=ALERTS_CHANNEL_ID)
                        else:
                            cause_result = await detect_unplanned_restart_cause(dt)
                            cause_text, pending_settings = cause_result or (None, None)
                            sent = await broadcast_embed(
                                "Server restarted unexpectedly",
                                None,
                                COLOR_SHUTDOWN,
                                dt,
                                channel_id=ALERTS_CHANNEL_ID,
                                fields=[("Likely cause", cause_text or "Unknown — an admin will need to check the server logs.")],
                            )
                            if sent and pending_settings is not None:
                                save_last_palworld_settings(pending_settings)
                    elif m := VERSION_RE.search(msg):
                        if not restart_module._bot_restart_in_progress:
                            await broadcast_embed("Server is online", f"Game version: `{m.group(1)}`", COLOR_READY, dt, channel_id=ALERTS_CHANNEL_ID)
                        await check_palworld_settings_change()
            log.warning("log tailer: journalctl stream ended, restarting in 5s")
        except Exception:
            log.exception("log tailer crashed, restarting in 5s")
        await asyncio.sleep(5)
```

- [ ] **Step 2: Syntax-check**

Run: `python -m py_compile swee/log_tailer.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add swee/log_tailer.py
git commit -m "refactor: extract log_tailer.py from main.py"
```

---

### Task 13: `commands.py`

**Files:**
- Create: `swee/commands.py`

**Interfaces:**
- Consumes: `swee.bot.{bot, in_commands_channel, is_admin}`, `swee.config.{COLOR_CHAT, COLOR_SHUTDOWN, OFFLINE_PLAYERS_LIMIT}`, `swee.embeds.{add_status_fields, format_offline_field, format_online_field, offline_entries_from_history}`, `swee.player_history.{online_players, player_history, refresh_online_players, session_started}`, `swee.rest_client.rest`, `swee.restart` (module, for `_bot_restart_in_progress`), `swee.restart.restart_palworld`
- Produces: registers `/status`, `/players`, `/save`, `/kick`, `/ban`, `/broadcast`, `/restart` on `bot.tree`, plus `on_app_command_error` error handler. Importing this module for its side effects (the `@bot.tree.command` decorators) is what registers the commands — `main.py` must `import swee.commands` even though nothing calls it directly.

- [ ] **Step 1: Write `swee/commands.py`**

```python
import logging

import discord
from discord import app_commands

import swee.restart as restart_module
from swee.bot import bot, in_commands_channel, is_admin
from swee.config import COLOR_CHAT, COLOR_SHUTDOWN, OFFLINE_PLAYERS_LIMIT
from swee.embeds import add_status_fields, format_offline_field, format_online_field, offline_entries_from_history
from swee.player_history import online_players, player_history, refresh_online_players, session_started
from swee.rest_client import rest
from swee.restart import restart_palworld

log = logging.getLogger("swee")


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
```

- [ ] **Step 2: Syntax-check**

Run: `python -m py_compile swee/commands.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add swee/commands.py
git commit -m "refactor: extract commands.py from main.py"
```

---

### Task 14: Rewrite `main.py`, update `README.md`, and verify the whole package

**Files:**
- Modify: `main.py` (full rewrite — replace the entire file)
- Modify: `README.md:18` (the `CAUSE_DETECTORS` reference)

**Interfaces:**
- Consumes: everything produced by Tasks 1-13
- Produces: `on_message` / `on_ready` event handlers, `main()` coroutine, process entrypoint (unchanged external behavior — same systemd `ExecStart` still works)

- [ ] **Step 1: Replace `main.py` with the thin composition root**

```python
import asyncio
import logging

import discord

import swee.commands  # noqa: F401 — registers slash commands via decorator side effects
from swee.bot import bot
from swee.cause_detection import load_last_palworld_settings
from swee.config import BOT_TOKEN, GUILD_ID, RELAY_CHANNEL_ID
from swee.log_tailer import log_tailer
from swee.player_history import load_player_history
from swee.releases import load_last_release, release_ticker
from swee.rest_client import rest
from swee.restart import check_palworld_service
from swee.stats import stats_ticker

log = logging.getLogger("swee")

_log_tailer_task = None  # keeps a strong reference so asyncio doesn't GC it mid-run


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
```

- [ ] **Step 2: Update the `README.md` reference to `CAUSE_DETECTORS`**

Find the line (currently `README.md:18`):
```
  detectors (`CAUSE_DETECTORS` in `main.py`) — currently one, which recognizes an
```
Replace with:
```
  detectors (`CAUSE_DETECTORS` in `swee/cause_detection.py`) — currently one, which recognizes an
```

- [ ] **Step 3: Syntax-check the new `main.py`**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0.

- [ ] **Step 4: Full import smoke test with a throwaway `.env`**

This is the one point where we verify the *entire* import graph resolves — every module actually
imports the others correctly, not just parses. Since no `.env` exists in this dev environment (and
none should be committed), create a temporary one with dummy values matching `.env.example`, run
the import, then delete it:

```bash
cat > .env <<'EOF'
DISCORD_BOT_TOKEN=dummy
GUILD_ID=123456789012345678
ADMIN_ROLE_ID=123456789012345678
STATS_CHANNEL_ID=123456789012345678
ACTIVITY_CHANNEL_ID=123456789012345678
ALERTS_CHANNEL_ID=123456789012345678
ADMIN_CHANNEL_ID=123456789012345678
COMMANDS_CHANNEL_ID=123456789012345678
BOT_UPDATES_CHANNEL_ID=123456789012345678
REST_HOST=127.0.0.1
REST_PORT=8212
REST_USER=admin
REST_PASSWORD=dummy
GITHUB_REPO=byroncustodio/swee
PALWORLD_SETTINGS_INI_PATH=/tmp/does-not-exist.ini
EOF
python -c "import main" && echo IMPORT_OK
rm .env
```

Expected: `IMPORT_OK` printed, no `ImportError`/`AttributeError`/`ModuleNotFoundError` traceback.
(A `KeyError` here would mean a required env var was missed in the dummy file, not a bug in the
split — double check against `.env.example` if that happens.)

- [ ] **Step 5: Read-through check — every original top-level name has exactly one new home**

Diff the old `main.py` (available via `git show HEAD:main.py` before this task's commit) against
the union of all `swee/*.py` files plus the new `main.py`. Confirm every function, class, and
module-level constant from the original file appears exactly once. Confirm no name was dropped or
duplicated.

Run: `git show HEAD:main.py | grep -E "^(def |class |[A-Z_]+ ?=|async def )" `
Expected: every name in this list appears in exactly one file under the new `swee/` package or the
new `main.py`.

- [ ] **Step 6: Commit**

```bash
git add main.py README.md
git commit -m "refactor: rewrite main.py as a thin composition root over swee/"
```

---

## Post-plan verification (manual, not automatable here)

This split cannot be fully exercised without a live Palworld server, Discord bot token, and guild —
none of which exist in this dev environment. Before merging, deploy the branch to a real (or
staging) host per `README.md`'s `deploy/setup.sh` flow and confirm:
- The bot logs in and slash commands sync (`/status`, `/players`, `/save`, `/kick`, `/ban`,
  `/broadcast`, `/restart` all appear in Discord).
- Player join/leave events post to the activity channel and update the pinned stats embed.
- `/restart` completes and posts a result embed.
- The RAM auto-restart and release-announcement tickers still fire (can wait for their natural
  interval or temporarily lower `RAM_RESTART_THRESHOLD_PCT` / the release-ticker interval to check
  sooner, then revert).
