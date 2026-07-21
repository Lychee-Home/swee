# palfeed Owner Name Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve `palfeed`'s catch-event `owner_player_uid` (a save-file GUID) to the in-game player name, and show it as an "Owner" field on notable-catch embeds when known.

**Architecture:** Two small additions to `swee/player_history.py` (a `"player_id"` field stored alongside each existing `player_history[userId]` entry, and a new `resolve_owner_name()` lookup function), plus one call site change in `swee/palfeed.py`'s `format_catch_embed`. No new files, no new persistence — reuses the existing `player_history.json` write path.

**Tech Stack:** Python 3.14, stdlib `unittest`.

## Global Constraints

- The REST API's `playerId` field (e.g. `D3609521000000000000000000000000` — uppercase, no dashes, 32 hex chars) and `palsave-api`'s `owner_player_uid` field (e.g. `d3609521-0000-0000-0000-000000000000` — lowercase, dashed) are the same underlying GUID, confirmed live against the deployed server. `resolve_owner_name` normalizes the dashed form (strip dashes, uppercase) to match the stored form — the stored form itself needs no transformation, since that's already the shape the REST API returns it in.
- `player_history[userId]["player_id"]` is populated at the two existing call sites that already write `name`/`last_seen` from REST player data (`record_join`, `refresh_online_players`) — both already receive REST player dicts that include `playerId`.
- `record_leave` does **not** have REST player data available (it only knows `name`/`uid` at leave time) — it must preserve whatever `player_id` was already stored for that `uid`, not silently drop it by constructing a fresh dict without the field.
- Entries written before this change (or by `record_leave` for a player who was never seen by `record_join`/`refresh_online_players` post-upgrade) won't have a `player_id` key — `resolve_owner_name` must treat a missing key the same as "no match" (`None`), no migration needed.
- No new file, no new env var, no new Discord-account mapping — only the in-game display name, added as a field, omitted when unresolvable.
- Run tests with `python -m unittest discover tests -v` from the repo root. New tests for `resolve_owner_name` must follow `tests/test_releases.py`'s existing pattern of stubbing required env vars with `os.environ.setdefault(...)` before importing (since `swee/player_history.py` imports `swee.config`/`swee.rest_client`, which require a populated `.env` to import).

---

### Task 1: Owner name resolution + embed field

**Files:**
- Modify: `swee/player_history.py:69-76` (`record_join`), `swee/player_history.py:79-89` (`record_leave`), `swee/player_history.py:92-105` (`refresh_online_players`), plus a new `resolve_owner_name` function
- Modify: `swee/palfeed.py:46-52` (`format_catch_embed`)
- Test: `tests/test_player_history.py`

**Interfaces:**
- Consumes: `swee.player_history.player_history` (existing module-global dict, `userId -> {"name": str, "last_seen": str, ...}`, mutated in place per the existing convention documented at `swee/player_history.py:20-23`).
- Produces: `swee.player_history.resolve_owner_name(player_uid: str | None) -> str | None`. Consumed by `swee/palfeed.py`'s `format_catch_embed`, which already receives an `event` dict containing `owner_player_uid` (str or `None`) from `palsave-api`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_player_history.py`:

```python
import os
import unittest

# swee.config reads required settings from the environment at import time; player_history.py
# imports it (and swee.rest_client), so stub the env before importing, same as test_releases.py.
os.environ.setdefault("DISCORD_BOT_TOKEN", "x")
os.environ.setdefault("GUILD_ID", "1")
os.environ.setdefault("ADMIN_ROLE_ID", "1")
os.environ.setdefault("RELAY_CHANNEL_ID", "1")
os.environ.setdefault("STATS_CHANNEL_ID", "1")
os.environ.setdefault("ACTIVITY_CHANNEL_ID", "1")
os.environ.setdefault("ALERTS_CHANNEL_ID", "1")
os.environ.setdefault("ADMIN_CHANNEL_ID", "1")
os.environ.setdefault("COMMANDS_CHANNEL_ID", "1")
os.environ.setdefault("BOT_UPDATES_CHANNEL_ID", "1")
os.environ.setdefault("REST_HOST", "x")
os.environ.setdefault("REST_PORT", "1")
os.environ.setdefault("REST_USER", "x")
os.environ.setdefault("REST_PASSWORD", "x")
os.environ.setdefault("PALWORLD_SETTINGS_INI_PATH", "/tmp/x")
os.environ.setdefault("PALWORLD_INSTALL_DIR", "/tmp")

from swee.player_history import player_history, resolve_owner_name  # noqa: E402


class ResolveOwnerNameTests(unittest.TestCase):
    def setUp(self):
        player_history.clear()

    def tearDown(self):
        player_history.clear()

    def test_resolves_dashed_lowercase_guid_to_name(self):
        player_history["steam_1"] = {
            "name": "Kippei",
            "last_seen": "2026-07-20T00:00:00-07:00",
            "player_id": "97398A79000000000000000000000000",
        }
        self.assertEqual(resolve_owner_name("97398a79-0000-0000-0000-000000000000"), "Kippei")

    def test_returns_none_for_unknown_guid(self):
        player_history["steam_1"] = {
            "name": "Kippei",
            "last_seen": "2026-07-20T00:00:00-07:00",
            "player_id": "97398A79000000000000000000000000",
        }
        self.assertIsNone(resolve_owner_name("00000000-0000-0000-0000-000000000000"))

    def test_returns_none_for_none_input(self):
        self.assertIsNone(resolve_owner_name(None))

    def test_returns_none_when_no_players_tracked(self):
        self.assertIsNone(resolve_owner_name("97398a79-0000-0000-0000-000000000000"))

    def test_ignores_entries_missing_player_id(self):
        # Entries written before this feature existed (or by record_leave for a player never
        # seen by record_join/refresh_online_players post-upgrade) have no player_id key.
        player_history["steam_1"] = {"name": "Legacy", "last_seen": "2026-07-20T00:00:00-07:00"}
        self.assertIsNone(resolve_owner_name("97398a79-0000-0000-0000-000000000000"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_player_history -v`
Expected: FAIL / ERROR — `ImportError: cannot import name 'resolve_owner_name' from 'swee.player_history'`

- [ ] **Step 3: Add `player_id` storage and `resolve_owner_name` to swee/player_history.py**

In `swee/player_history.py`, change `record_join` (currently lines 58-76) from:

```python
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
            save_session_state()
            return
```

to:

```python
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
            player_history[uid] = {"name": name, "last_seen": dt.isoformat(), "player_id": p.get("playerId")}
            player_history.pop(f"name:{name}", None)  # supersede any stale fallback-key entry
            save_player_history()
            save_session_state()
            return
```

Change `record_leave` (currently lines 79-89) from:

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
    save_session_state()
```

to:

```python
async def record_leave(name, dt):
    uid = online_players.pop(name, None)
    session_started.pop(name, None)
    if uid is None:
        uid = next((k for k, v in player_history.items() if v["name"] == name), None)
    if uid is None:
        uid = f"name:{name}"
        log.warning("player history: no stable ID found for %s on leave, using fallback key", name)
    # Preserve any previously-recorded player_id — this rewrite has no fresh REST data to draw
    # from, so a naive fresh dict here would silently drop it.
    player_id = player_history.get(uid, {}).get("player_id")
    player_history[uid] = {"name": name, "last_seen": dt.isoformat(), "player_id": player_id}
    save_player_history()
    save_session_state()
```

Change `refresh_online_players` (currently lines 92-105) from:

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
    save_session_state()
```

to:

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
        player_history[uid] = {"name": p["name"], "last_seen": now_iso, "player_id": p.get("playerId")}
        player_history.pop(f"name:{p['name']}", None)  # supersede any stale fallback-key entry
    save_player_history()
    save_session_state()
```

Add this function at the end of `swee/player_history.py` (after `refresh_online_players`):

```python
def resolve_owner_name(player_uid):
    """Look up the current display name for a save-file PlayerUId GUID (e.g.
    "d3609521-0000-0000-0000-000000000000", as palsave-api's diff.py formats it), by matching
    against the REST API's playerId shape (uppercase, no dashes) stored in player_history.
    Returns None if the GUID has never been seen (or player_uid is None/empty) — no migration
    needed for entries predating this field.
    """
    if not player_uid:
        return None
    normalized = player_uid.replace("-", "").upper()
    for entry in player_history.values():
        if entry.get("player_id") == normalized:
            return entry["name"]
    return None
```

Also update the type comment at `swee/player_history.py:14` from:

```python
player_history = {}   # userId -> {"name": str, "last_seen": ISO8601 str}
```

to:

```python
player_history = {}   # userId -> {"name": str, "last_seen": ISO8601 str, "player_id": str | None}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_player_history -v`
Expected: `OK` (5 tests passed)

- [ ] **Step 5: Wire resolve_owner_name into swee/palfeed.py's format_catch_embed**

In `swee/palfeed.py`, add the import (after the existing `swee.palfeed_notability` import on line 9):

```python
from swee.player_history import resolve_owner_name
```

Change `format_catch_embed` (currently lines 46-52) from:

```python
def format_catch_embed(event, tier):
    title = f"{event.get('character_id') or 'Unknown Pal'} — {tier}"
    acquisition = ACQUISITION_LABELS.get(event.get("acquisition_type"), "Acquired")
    level = event.get("level")
    description = acquisition + (f" — Level {level}" if level is not None else "")
    fields = [("Talent Score", f"{talent_score(event)}/300")]
    return title, description, fields
```

to:

```python
def format_catch_embed(event, tier):
    title = f"{event.get('character_id') or 'Unknown Pal'} — {tier}"
    acquisition = ACQUISITION_LABELS.get(event.get("acquisition_type"), "Acquired")
    level = event.get("level")
    description = acquisition + (f" — Level {level}" if level is not None else "")
    fields = [("Talent Score", f"{talent_score(event)}/300")]
    owner_name = resolve_owner_name(event.get("owner_player_uid"))
    if owner_name:
        fields.append(("Owner", owner_name))
    return title, description, fields
```

- [ ] **Step 6: Run the full test suite (regression check)**

Run: `python -m unittest discover tests -v`
Expected: `OK` — all existing tests plus this step's 5 new `test_player_history` tests pass. `swee/palfeed.py` itself remains untested beyond this (it needs a populated `.env` to import, same precedent as before).

- [ ] **Step 7: Commit**

```bash
git add swee/player_history.py swee/palfeed.py tests/test_player_history.py
git commit -m "feat: resolve pal catch owner name in palfeed embeds"
```

---

## Self-Review

**Spec coverage:** `player_id` storage at `record_join`/`refresh_online_players`, preserved (not dropped) at `record_leave` ✓; `resolve_owner_name` normalization + linear scan + `None` on no match ✓; `format_catch_embed`'s new `Owner` field, omitted when unresolved ✓; no new file/persistence/env var ✓; testing follows `test_releases.py`'s env-stub pattern ✓.

**Placeholder scan:** none — every step has complete code.

**Type consistency:** `resolve_owner_name(player_uid)` (defined Step 3) is imported and called with the same name/argument shape in Step 5's `format_catch_embed`. Test file (Step 1) imports `resolve_owner_name` from the same module path it's added to in Step 3.
