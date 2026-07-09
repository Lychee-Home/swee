# Show time-online instead of ping in the Online field — design

## Problem

The stats embed's `Online` field (`format_online_field()`, main.py:208-211) shows
`**name** — Lv.X (Yms)` — level and ping. Ping is a low-value, noisy number for a Discord
status view; how long someone's been playing this session is more useful. We want to replace
ping with a live-updating "joined N ago" timestamp.

## Scope

Replace the ping portion of each Online line with a Discord relative-time tag
(`<t:UNIXTIME:R>`) showing when that player joined — same rendering mechanism already used for
the Offline field's last-seen timestamps. New line format:
`**name** — Lv.X — <t:UNIXTIME:R>`.

Out of scope: the Offline field, `/players` (a separate, pre-existing command with its own
ping-based format — untouched), any change to `player_history.json`'s on-disk schema (this
adds new in-memory-only state, not persisted).

## Data model

New module-level dict, declared alongside `online_players` (main.py:137):

```python
session_started = {}  # display name -> ISO8601 join timestamp string, cleared on leave
```

Not persisted to `player_history.json` — it only describes *current* sessions, and is
naturally rebuilt/self-healed on every ticker tick and join event, so there's nothing worth
surviving a bot restart (see "Missing join time" below for what happens across a restart).

## Behavior

**`record_join(name, dt)` (main.py:159-172):** on a successful match, also set
`session_started[name] = dt.isoformat()` — this is a real, log-line-derived join time.

**`record_leave(name, dt)` (main.py:175-183):** pop `session_started[name]` — the session is
over, nothing left to time.

**`refresh_online_players(players_list)` (main.py:186-194):** for each currently-online player,
set `session_started[name] = now_iso` **only if `name` isn't already a key** (don't clobber a
real join time already recorded by `record_join`). Then prune any `session_started` keys not
present in this tick's `players_list` — covers a missed leave event (log tailer restart,
dropped line) so a stale timer doesn't linger for someone who's actually gone.

**Missing join time (bot restart / missed join event):** the first ticker tick after the bot
starts (or after any missed join), a player already online gets `session_started[name] =
now_iso` via the fallback above — i.e. their displayed "joined X ago" starts counting from when
*this bot* first noticed them, not their real Palworld session start. This under-counts actual
playtime in that case but always shows something reasonable and requires no persistence.

## Rendering

`format_online_field(players, session_started)` (main.py:208-211), new signature:

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
            when = "just now"  # first tick after refresh_online_players sets it; see note below
        lines.append(f"**{p['name']}** — Lv.{p['level']} — {when}")
    return "\n".join(lines)
```

Note: in practice `session_started.get(p["name"])` should never be `None` by the time
`format_online_field` runs, because both call sites (`update_stats_message()` and `/status`)
call `refresh_online_players(players_list)` before rendering, which guarantees every name in
`players_list` has a `session_started` entry (real or fallback). The `"just now"` branch is
defensive, not an expected path — kept so a future call site that renders without refreshing
first degrades gracefully instead of crashing on `datetime.fromisoformat(None)`.

Both call sites (main.py ~292 in `update_stats_message()`, ~455 in `/status`) update their
`format_online_field(players)` call to `format_online_field(players, session_started)`.

## Error handling

No new failure modes: `session_started` is plain in-memory state mutated by the same
try/except-guarded call sites already handling `rest.players()` failures
(`record_join`, `update_stats_message`, `/status`). No new I/O.

## Non-goals / risks accepted

- Session duration resets to "just now" on a missed join or bot restart rather than showing
  their true Palworld session length — accepted per the "Missing join time" behavior above,
  consistent with this feature not persisting session state.
- No test suite exists in this repo (per CLAUDE.md); verification is manual — join the real
  server, confirm the Online field shows a live-updating "joined X ago", restart the bot while
  someone's online and confirm their timer resets to "joined just now" on the next tick.
