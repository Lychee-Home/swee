# Persist session_started across bot restarts — design

## Problem

The stats embed's "Online" field shows each player's session length via a Discord relative
timestamp (`format_online_field()`, `swee/embeds.py`), driven by `session_started` in
`swee/player_history.py` — a display-name-to-ISO8601-join-timestamp dict. That dict is
explicitly in-memory only (see `docs/superpowers/specs/2026-07-08-online-time-display-design.md`),
so any bot restart while players are online resets their displayed join time to "just now,"
even though their real Palworld session is still ongoing.

## Scope

Persist `session_started` to disk so a bot restart doesn't lose real join times for players who
are still online when the bot comes back up. Out of scope: `player_history.json`'s schema (untouched),
any change to how `session_started` is mutated in memory, any new reconciliation logic beyond what
already exists.

## Data model

New file, `session_state.json`, storing the `session_started` dict verbatim (display name ->
ISO8601 join timestamp string) — same shape as the in-memory dict, no transformation. Kept
separate from `player_history.json` because the two model different things: `player_history.json`
is a userId-keyed durable history of last-seen times; `session_started` is a name-keyed live-session
concept, transient by nature (a name can be reused across characters/sessions), that just happens
to now also need to survive a restart.

## Behavior

`swee/player_history.py` gets two new functions, mirroring the existing `load_player_history()` /
`save_player_history()` pair:

```python
SESSION_STATE_PATH = "session_state.json"

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

`save_session_state()` is called at the same three points that already call `save_player_history()`:
end of `record_join()`, end of `record_leave()`, end of `refresh_online_players()`.

`load_session_state()` is called in `main.py`, alongside the existing `load_player_history()` call
(`main.py:53`), before the bot starts.

## Reconciliation (no new logic needed)

`refresh_online_players()` already prunes any `session_started` key not present in the current
tick's live `players()` result (`swee/player_history.py:77-78`), and it runs on every stats-embed
update and every `/status` invocation. So after a restart:

- A player who is still online when the bot restarts: their real `session_started` entry was
  loaded from disk and is preserved — the "joined X ago" timestamp is accurate across the restart.
- A player who logged off while the bot was down: their stale `session_started` entry is dropped
  on the very first post-restart tick, same as the existing missed-leave-event handling.

## Error handling

Identical failure modes to `player_history.json`: missing file on load starts with empty state
(first-run / fresh-deploy case), corrupt file logs a warning and starts empty rather than crashing.
No new I/O paths — `save_session_state()` runs at existing synchronous save points, no new
try/except needed since file writes to the local filesystem aren't expected to fail under normal
operation (consistent with how `save_player_history()` is already handled).

## Non-goals / risks accepted

- No migration of any existing data — `session_state.json` doesn't exist yet, so there's nothing
  to convert.
- No change to `player_history.json`'s on-disk schema.
- If the bot is down long enough that a player logs off *and back on* before it restarts, the
  restored `session_started` entry would show their *first* join time from before the bot went
  down, not their more recent one — same class of drift the original design already accepted for
  missed events, not worsened by this change.
- No test suite exists in this repo (per CLAUDE.md) for the Discord command layer; verification is
  manual — join the real server, restart the bot while online, confirm the Online field's "joined
  X ago" timestamp is unchanged (not reset) after the restart; then leave, restart again, rejoin,
  and confirm a fresh entry is created correctly.
