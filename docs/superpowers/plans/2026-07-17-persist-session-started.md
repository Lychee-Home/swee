# Persist session_started across bot restarts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a bot restart no longer reset the "joined X ago" timer shown in the stats embed's
Online field for players who are still online across the restart.

**Architecture:** Add a `session_state.json` file, persisted with the same load/save pattern
already used for `player_history.json` in `swee/player_history.py`. Save on every existing
mutation of `session_started` (join, leave, refresh tick); load once at bot startup in `main.py`.
No new reconciliation logic — `refresh_online_players()` already prunes stale entries against the
live Palworld player list on every tick, so a restored session for someone who logged off while
the bot was down gets dropped automatically on the first post-restart tick.

**Tech Stack:** Python 3.14, stdlib `json` — no new dependencies.

## Global Constraints

- No test suite exists for the Discord command layer or for `player_history.py`'s existing
  load/save functions (per `CLAUDE.md`) — this plan does not add one, consistent with the spec's
  "Non-goals" section, which calls for manual verification instead.
- Follow the exact error-handling pattern of `load_player_history()` / `save_player_history()`
  (`swee/player_history.py:25-38`): `FileNotFoundError` → start empty, `json.JSONDecodeError` →
  log a warning and start empty, no try/except around the write.

---

### Task 1: Add session_state.json persistence functions and wire them into every session_started mutation

**Files:**
- Modify: `swee/player_history.py`

**Interfaces:**
- Consumes: existing module-level `session_started` dict (`swee/player_history.py:15`), stdlib
  `json`, module-level `log`.
- Produces: `SESSION_STATE_PATH` (str constant), `load_session_state()` (no args, returns None,
  mutates `session_started` in place), `save_session_state()` (no args, returns None, reads
  `session_started`). Both consumed by Task 2 (`main.py`) and already-existing call sites within
  this same file.

- [ ] **Step 1: Add the `SESSION_STATE_PATH` constant next to `PLAYER_HISTORY_PATH`**

In `swee/player_history.py`, change:

```python
PLAYER_HISTORY_PATH = "player_history.json"
player_history = {}   # userId -> {"name": str, "last_seen": ISO8601 str}
online_players = {}   # display name -> userId, refreshed on join/leave/tick
session_started = {}  # display name -> ISO8601 join timestamp, cleared on leave (not persisted)
```

to:

```python
PLAYER_HISTORY_PATH = "player_history.json"
SESSION_STATE_PATH = "session_state.json"
player_history = {}   # userId -> {"name": str, "last_seen": ISO8601 str}
online_players = {}   # display name -> userId, refreshed on join/leave/tick
session_started = {}  # display name -> ISO8601 join timestamp, cleared on leave, persisted to SESSION_STATE_PATH
```

- [ ] **Step 2: Add `load_session_state()` and `save_session_state()` after `save_player_history()`**

In `swee/player_history.py`, immediately after the existing `save_player_history()` function
(currently ending at line 38), add:

```python
def load_session_state():
    session_started.clear()
    try:
        with open(SESSION_STATE_PATH) as f:
            session_started.update(json.load(f))
    except FileNotFoundError:
        pass
    except json.JSONDecodeError:
        log.warning("session_state.json is corrupt, starting with empty session state")


def save_session_state():
    with open(SESSION_STATE_PATH, "w") as f:
        json.dump(session_started, f, indent=2)
```

- [ ] **Step 3: Call `save_session_state()` at the end of `record_join()`**

In `swee/player_history.py`, `record_join()` currently ends:

```python
            player_history[uid] = {"name": name, "last_seen": dt.isoformat()}
            player_history.pop(f"name:{name}", None)  # supersede any stale fallback-key entry
            save_player_history()
            return
```

Change to:

```python
            player_history[uid] = {"name": name, "last_seen": dt.isoformat()}
            player_history.pop(f"name:{name}", None)  # supersede any stale fallback-key entry
            save_player_history()
            save_session_state()
            return
```

- [ ] **Step 4: Call `save_session_state()` at the end of `record_leave()`**

In `swee/player_history.py`, `record_leave()` currently ends:

```python
    player_history[uid] = {"name": name, "last_seen": dt.isoformat()}
    save_player_history()
```

Change to:

```python
    player_history[uid] = {"name": name, "last_seen": dt.isoformat()}
    save_player_history()
    save_session_state()
```

- [ ] **Step 5: Call `save_session_state()` at the end of `refresh_online_players()`**

In `swee/player_history.py`, `refresh_online_players()` currently ends:

```python
        player_history[uid] = {"name": p["name"], "last_seen": now_iso}
        player_history.pop(f"name:{p['name']}", None)  # supersede any stale fallback-key entry
    save_player_history()
```

Change to:

```python
        player_history[uid] = {"name": p["name"], "last_seen": now_iso}
        player_history.pop(f"name:{p['name']}", None)  # supersede any stale fallback-key entry
    save_player_history()
    save_session_state()
```

- [ ] **Step 6: Verify the module imports cleanly**

Run: `python -c "import swee.player_history"`
Expected: no output, exit code 0 (confirms no syntax errors were introduced).

- [ ] **Step 7: Run the existing test suite to confirm no regressions**

Run: `python -m unittest discover tests -v`
Expected: all existing tests pass (this file has no direct test coverage, but `tests/` covers
`swee/palworld_settings.py` — confirms the change didn't break imports or collection).

- [ ] **Step 8: Commit**

```bash
git add swee/player_history.py
git commit -m "feat: persist session_started to session_state.json"
```

---

### Task 2: Load session_state.json at bot startup

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes: `load_session_state()` from Task 1 (`swee/player_history.py`).
- Produces: nothing new consumed elsewhere — this is the final wiring step.

- [ ] **Step 1: Import and call `load_session_state()` alongside `load_player_history()`**

In `main.py`, the import currently reads:

```python
from swee.player_history import load_player_history
```

Change to:

```python
from swee.player_history import load_player_history, load_session_state
```

In `main.py`, `main()` currently reads:

```python
    load_player_history()
    load_last_release()
    load_last_palworld_settings()
```

Change to:

```python
    load_player_history()
    load_session_state()
    load_last_release()
    load_last_palworld_settings()
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python -c "import main"`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: load persisted session_started at bot startup"
```

---

### Task 3: Manual verification on the live server

**Files:** none (no code changes — verification only, per the spec's Non-goals section: no
automated test harness exists for the Discord command layer).

- [ ] **Step 1: Deploy the branch to the host running the bot (per `docs/deployment.md`) or run it locally against the real Palworld REST API**

- [ ] **Step 2: Join the Palworld server as a player, confirm the stats embed's Online field shows a live "joined X ago" timestamp for that player**

- [ ] **Step 3: Restart the bot process while that player is still online**

Expected: after restart, `session_state.json` exists on disk in the working directory and
contains the player's name and original join timestamp.

- [ ] **Step 4: Wait for the next stats embed tick (or run `/status`) and confirm the Online field still shows the *original* join time, not "just now"**

- [ ] **Step 5: Have the player leave the server, restart the bot again, then have a different (or the same) player join fresh**

Expected: `session_started` in `session_state.json` no longer contains the player who left (pruned
by `refresh_online_players()` on the first tick), and the newly-joined player gets a fresh,
correct entry.

- [ ] **Step 6: No commit for this task** — verification only, confirms Tasks 1-2 work end to end.
