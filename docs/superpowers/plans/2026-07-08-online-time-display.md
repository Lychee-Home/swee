# Show time-online instead of ping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ping shown per player in the stats embed's `Online` field with a
live-updating "joined N ago" relative timestamp.

**Architecture:** A new module-level dict `session_started` (display name -> ISO join
timestamp) is set from a real join event when available, or a "first noticed online" fallback
on the ticker/refresh path, and cleared on leave. `format_online_field()` renders it as a
Discord `<t:UNIXTIME:R>` tag, the same mechanism already used for the Offline field.

**Tech Stack:** Python 3.13, discord.py, httpx (existing — no new dependencies).

## Global Constraints

- No automated test runner exists in this repo (per `CLAUDE.md`) — verification is manual,
  either via a standalone `python -c` snippet for the pure formatting function or live testing
  against the real server.
- All bot logic lives in `main.py` — no new modules.
- `session_started` is in-memory only, not persisted to `player_history.json` (spec: "Data
  model").
- Spec: `docs/superpowers/specs/2026-07-08-online-time-display-design.md`.

---

### Task 1: Track and render session start time in the Online field

**Files:**
- Modify: `main.py:137` (module state, add `session_started`)
- Modify: `main.py:159-172` (`record_join`)
- Modify: `main.py:175-183` (`record_leave`)
- Modify: `main.py:186-194` (`refresh_online_players`)
- Modify: `main.py:208-211` (`format_online_field`)
- Modify: the two call sites of `format_online_field(players)` — inside `update_stats_message()`
  (currently around main.py:292's `add_status_fields(...)` call, which internally calls
  `format_online_field(players)`) and inside `add_status_fields()` itself (main.py: the function
  containing `embed.add_field(name="Online", value=format_online_field(players), ...)`)

**Interfaces:**
- Produces: `session_started: dict[str, str]` (display name -> ISO8601 join timestamp),
  `format_online_field(players: list[dict], session_started: dict) -> str` (signature change
  from the current `format_online_field(players)`).
- Consumes: `online_players`, `record_join`, `record_leave`, `refresh_online_players` (all
  pre-existing from the prior online/offline-tables feature).

- [ ] **Step 1: Add `session_started` module state**

Current (main.py:134-140):
```python
# ---------- Player history (online/offline tracking) ----------
PLAYER_HISTORY_PATH = "player_history.json"
player_history = {}   # userId -> {"name": str, "last_seen": ISO8601 str}
online_players = {}   # display name -> userId, refreshed on join/leave/tick
# Safe without _stats_lock only because these dicts are never mutated across an `await`
# (asyncio is single-threaded); if that changes, guard the mutation with _stats_lock.
```

New:
```python
# ---------- Player history (online/offline tracking) ----------
PLAYER_HISTORY_PATH = "player_history.json"
player_history = {}   # userId -> {"name": str, "last_seen": ISO8601 str}
online_players = {}   # display name -> userId, refreshed on join/leave/tick
session_started = {}  # display name -> ISO8601 join timestamp, cleared on leave (not persisted)
# Safe without _stats_lock only because these dicts are never mutated across an `await`
# (asyncio is single-threaded); if that changes, guard the mutation with _stats_lock.
```

- [ ] **Step 2: Set `session_started` on a real join in `record_join`**

Current (main.py:159-172):
```python
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
            player_history.pop(f"name:{name}", None)  # supersede any stale fallback-key entry
            save_player_history()
            return
```

New:
```python
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
```

- [ ] **Step 3: Clear `session_started` on leave in `record_leave`**

Current (main.py:175-183):
```python
async def record_leave(name, dt):
    uid = online_players.pop(name, None)
    if uid is None:
        uid = next((k for k, v in player_history.items() if v["name"] == name), None)
    if uid is None:
        uid = f"name:{name}"
        log.warning("player history: no stable ID found for %s on leave, using fallback key", name)
    player_history[uid] = {"name": name, "last_seen": dt.isoformat()}
    save_player_history()
```

New:
```python
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
```

- [ ] **Step 4: Set fallback `session_started` and prune stale entries in `refresh_online_players`**

Current (main.py:186-194):
```python
def refresh_online_players(players_list):
    online_players.clear()
    now_iso = datetime.now(timezone.utc).astimezone(PACIFIC).isoformat()
    for p in players_list:
        uid = p["userId"]
        online_players[p["name"]] = uid
        player_history[uid] = {"name": p["name"], "last_seen": now_iso}
        player_history.pop(f"name:{p['name']}", None)  # supersede any stale fallback-key entry
    save_player_history()
```

New:
```python
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

`session_started.setdefault(...)` only writes `now_iso` if the name isn't already a key —
so a real join time recorded by `record_join` is never overwritten by this fallback path.

- [ ] **Step 5: Change `format_online_field()` to render join time instead of ping**

Current (main.py:208-211):
```python
def format_online_field(players):
    if not players:
        return "No one online."
    return "\n".join(f"**{p['name']}** — Lv.{p['level']} ({round(p['ping'])}ms)" for p in players)
```

New:
```python
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
```

- [ ] **Step 6: Verify the formatting logic standalone**

Run:
```bash
python -c "
from datetime import datetime, timezone

def format_online_field(players, session_started):
    if not players:
        return 'No one online.'
    lines = []
    for p in players:
        joined_iso = session_started.get(p['name'])
        if joined_iso:
            ts = int(datetime.fromisoformat(joined_iso).timestamp())
            when = f'<t:{ts}:R>'
        else:
            when = 'just now'
        lines.append(f\"**{p['name']}** — Lv.{p['level']} — {when}\")
    return chr(10).join(lines)

assert format_online_field([], {}) == 'No one online.'

players = [{'name': 'Kippei', 'level': 39, 'ping': 64.28}]
out = format_online_field(players, {'Kippei': '2026-07-08T10:00:00+00:00'})
expected_ts = int(datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc).timestamp())
assert out == f'**Kippei** — Lv.39 — <t:{expected_ts}:R>', out

out_fallback = format_online_field(players, {})
assert out_fallback == '**Kippei** — Lv.39 — just now', out_fallback

print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 7: Update both call sites to pass `session_started`**

Find both call sites with:
```bash
grep -n "format_online_field(players)" main.py
```

Expected: two matches — one inside `add_status_fields()` (the `embed.add_field(name="Online",
value=format_online_field(players), ...)` line), and none elsewhere (there is only one
function that calls it; `update_stats_message()` and `/status` both call `add_status_fields()`,
they don't call `format_online_field` directly). Change the one call site from:

```python
embed.add_field(name="Online", value=format_online_field(players), inline=False)
```

to:

```python
embed.add_field(name="Online", value=format_online_field(players, session_started), inline=False)
```

(If `grep` finds a different number of matches than expected, stop and report — the file may
have diverged from what this plan assumes; don't guess at additional call sites.)

- [ ] **Step 8: Verify with `python -m py_compile`**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0.

- [ ] **Step 9: Commit**

```bash
git add main.py
git commit -m "Show time-online instead of ping in the stats embed's Online field"
```

---

### Task 2: Manual verification against the real server

**Files:** none (manual verification only — no code changes)

- [ ] **Step 1: Deploy and restart the bot**

Follow the existing deploy process to run the updated `main.py` on the Palworld host.

- [ ] **Step 2: Confirm a fresh join shows a live join timer**

Have a player join. Expected: within the join-triggered `update_stats_message()` call or the
next ticker tick, the `Online` field shows `**name** — Lv.X — <t:...:R>`, rendering in Discord
as "joined a few seconds ago" and counting up over time.

- [ ] **Step 3: Confirm a bot restart while someone's online shows the fallback**

With a player already online, restart the bot. Expected: on the next ticker tick after
startup, that player's Online entry shows "joined less than a minute ago" (the fallback
`now_iso` set by `refresh_online_players`), not their true original join time.

- [ ] **Step 4: Confirm `/status` matches**

Run `/status`. Expected: same Online field content/format as the pinned embed.

- [ ] **Step 5: Confirm leave clears the timer**

Have the player leave, then rejoin. Expected: their new Online entry shows a fresh "joined a
few seconds ago", not the stale time from their previous session.

No commit for this task — it's verification of the already-committed Task 1. If any step
fails, fix Task 1's code and commit a follow-up fix referencing this task.
