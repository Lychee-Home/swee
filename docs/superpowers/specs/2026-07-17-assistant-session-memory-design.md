# Per-player conversation sessions for the `@swee` assistant

## Problem

The `@swee` in-game assistant (`swee/assistant.py`, see
`docs/superpowers/specs/2026-07-17-ingame-assistant-design.md`) answers each question independently
— `ask_claude` builds a fresh `messages` list from scratch every call. A player asking a follow-up
("what about its passive skills?" after asking about a specific pal) gets no benefit from what they
already asked; each question is a cold start.

## Design

### Identity: userId, not display name

`swee/player_history.py` already treats a player's REST `userId` as their canonical identity —
`online_players` (name → `userId`) exists precisely because display names aren't guaranteed unique
or stable (renames, name collisions across accounts). Keying assistant state by display name would
risk two different players silently sharing a session, or a session breaking on rename.

A new helper in `swee/assistant.py` resolves a display name to that stable id:

```python
from swee.player_history import online_players

def resolve_player_id(name):
    return online_players.get(name, name)
```

Falls back to the display name itself if `online_players` doesn't have an entry yet (e.g. a
question asked inside the connect→join race window `log_tailer.py`'s `pending_connects` already
handles for join notifications). This import matches the existing precedent of `swee/commands.py`
importing `online_players` from `swee/player_history.py` — not a new kind of coupling.

Both the existing per-player cooldown (`_last_answered`) and the new session store are keyed by this
resolved id instead of raw display name, fixing the same rename/collision edge case for cooldown
enforcement at no extra cost (the id is already resolved at the same call site).

### Session storage

```python
_sessions = {}  # player id -> list of {"role": "user"|"assistant", "content": str}, capped at 16 (8 exchanges)
SESSION_HISTORY_LIMIT = 8
```

Each entry stores simplified text pairs, not the raw Anthropic message list — critically, **not**
the `tool_use`/`tool_result` blocks from a question's internal tool-call loop. Every question still
runs its own fresh tool-use loop inside `ask_claude`; only the *final outcome* of prior questions
(the question text and the answer text) carries forward as context for the next question. This keeps
stored history compact and avoids replaying stale `tool_use_id`s across turns (each API call's tool
loop is self-contained; only the surrounding conversation history persists).

Capped at 8 exchanges (16 messages): oldest pair dropped first once full. Sized from actual token/
cost estimates worked out during design — at Haiku pricing ($1/M in, $5/M out), a full 8-exchange
session costs roughly $0.0045/query, i.e. well under a dollar a month at realistic hobby-server
question volume, with cost/latency growing linearly per exchange retained.

### `ask_claude` gains history

```python
async def ask_claude(question, history=None):
    messages = list(history or []) + [{"role": "user", "content": question}]
    ...  # unchanged tool-use loop below
```

### `handle_mention` flow (updated)

1. `if _anthropic is None: return` (unchanged — feature fully inert when unconfigured).
2. `player_id = resolve_player_id(player_name)`.
3. Cooldown check/record now uses `player_id` instead of `player_name`.
4. `history = _sessions.get(player_id, [])`; call `ask_claude(question, history)`.
5. **Only on success** (not on the `except`-branch fallback/error text), append the new
   `{"role": "user", ...}` / `{"role": "assistant", ...}` pair to `_sessions[player_id]` and trim to
   the last `SESSION_HISTORY_LIMIT` exchanges. A transient failure (wiki lookup down, Anthropic API
   error) is not saved into the conversation, so it doesn't pollute future context with "sorry, I
   couldn't look that up" as if it were something the player actually asked about.
6. Broadcast (`rest.announce`) and the Discord log embed continue to use `player_name` for
   readability — only the internal dict keys change to `player_id`.

### Session clearing on logout

`swee/log_tailer.py`'s `LEAVE_RE` branch (`log_tailer.py:94-100`) currently calls `record_leave(name,
dt)`, which pops the player out of `online_players` as part of its own bookkeeping. The session-clear
must read the id *before* that happens:

```python
elif m := LEAVE_RE.search(rest_msg):
    name = m.group(1)
    if pending := pending_connects.pop(name, None):
        pending.cancel()
    uid = online_players.get(name)
    assistant.clear_session(uid or name)
    await broadcast_embed(f"{name} left the server", None, COLOR_LEAVE, dt)
    await record_leave(name, dt)
    await update_stats_message()
```

`clear_session` in `swee/assistant.py`:

```python
def clear_session(player_id):
    _sessions.pop(player_id, None)
```

A rejoin starts with no session entry, i.e. a fresh conversation — matches the "session" framing:
scoped to one connected play session, not persisted across logins.

### Testing

`resolve_player_id`, `clear_session`, and the session-append/trim logic are pure enough to unit test
directly (given a plain dict for `online_players`/`_sessions`, no network/Discord involved) — new
tests join the existing `tests/test_assistant.py` suite. `ask_claude`'s history-passing and the full
`handle_mention` orchestration remain integration-only, verified manually per this repo's existing
convention (no test harness for the log-tailer/Discord layer).

## Out of scope

- No persistence of sessions across bot restarts — in-memory only, matching every other
  session-scoped dict in this codebase (`pending_connects`, `online_players`, `_last_answered`).
- No inactivity timeout — logout is the only trigger that clears a session (see design discussion:
  an explicit timeout can be added later if long play sessions turn out to be a real problem).
- No extraction of a dedicated player-identity module — `assistant.py` imports `online_players`
  directly from `player_history.py`, matching `commands.py`'s existing precedent. Revisit only if
  `player_history.py` itself becomes unwieldy, not preemptively for this one import.
