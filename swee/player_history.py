import json
import logging
from datetime import datetime, timezone

import httpx

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
    except httpx.ConnectError:
        log.warning("player history: Palworld REST API unreachable, skipping join record for %s", name)
        return
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
