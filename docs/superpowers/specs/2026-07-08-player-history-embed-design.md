# Online/offline player tables in the stats embed — design

## Problem

The pinned stats embed (and `/status`) currently shows only a player count (`Players: 3/32`).
There's no way to see *who's* online, or when a player who isn't currently online was last
seen. We want to replace the count with two tables — online players (name/level/ping) and
offline players (name/last-seen) — so admins can tell who's around and who's been away without
digging through logs.

## Scope

Replace the single `Players` field in `add_status_fields()` (shared by the pinned stats embed
and `/status`) with two fields: `Online` and `Offline`.

- **Online**: live from `rest.players()`, same format `/players` already uses —
  `**name** — Lv.X (Yms)`, or `No one online.`
- **Offline**: players the bot has previously seen join/leave who aren't currently online,
  sorted by most-recently-seen first, capped at 10 (`OFFLINE_PLAYERS_LIMIT`), formatted
  `**name** — <t:UNIXTIME:R>` (Discord's native relative-time tag — renders as "2 hours ago",
  auto-updates client-side, localizes per viewer). `None yet.` if no history. `…and N more` if
  truncated.

Offline history must survive bot restarts, so it's persisted to a local JSON file.

Out of scope:
- No UI for browsing the *full* offline history beyond the top 10 — no new slash command for
  this. (Not requested; can be a follow-up.)
- No handling of players renaming their in-game display name — a rename is treated as a new
  identity only insofar as the *display* name shown will just reflect whatever name was most
  recently recorded for that `userId`; no rename history is kept.
- No cross-referencing with Discord accounts/roles.

## Data model & persistence

New file `player_history.json` (repo root, gitignored), holding:

```json
{
  "steam_76561198079227227": {"name": "Kippei", "last_seen": "2026-07-08T14:32:00-07:00"}
}
```

Keyed by the player's stable `userId` from the Palworld REST API's `/v1/api/players` response
(confirmed live: `{"name", "accountName", "playerId", "userId", "ip", "ping", "location_x",
"location_y", "level"}` — `userId` is the `steam_XXXXXXXXXXXXXXXXX` value, the same identifier
`/kick` and `/ban` already accept as `steamid`). Using this instead of raw display name means
two different accounts that happen to share a display name, or an account that gets renamed,
don't collide or lose history across sessions.

Loaded into an in-memory dict (`player_history: dict[str, dict]`) at startup. Missing or
corrupt file → start with an empty dict, `log.warning`, and the file is recreated on the next
write. Writes are a plain synchronous `json.dump` (small file, infrequent writes — at most once
a minute plus join/leave events — no need for async I/O or a database).

## Resolving log-line names to stable IDs

The join/leave log lines (`JOIN_RE`/`LEAVE_RE`) only ever contain a display name — no ID. The
REST `players()` response has the ID but only for players currently online. So IDs get attached
at join time and carried forward:

- **`online_players: dict[str, str]`** (module-level, alongside `player_history`) — maps
  currently-online display name → `userId`, rebuilt/refreshed continuously (see below). This is
  separate from `player_history` because it only reflects *who's online right now*.

- **On join** (`JOIN_RE` match in `log_tailer()`): call `rest.players()`, find the entry whose
  `name` matches the joining player, set `online_players[name] = userId`, and update
  `player_history[userId] = {"name": name, "last_seen": <join dt, ISO>}`. Persist.

- **On leave** (`LEAVE_RE` match): pop `online_players.pop(name, None)` to get the `userId`.
  - If found: update `player_history[userId]["last_seen"] = <leave dt, ISO>`, persist.
  - If not found (e.g. bot restarted mid-session and missed the join): search
    `player_history` for an entry whose `"name"` matches; if found, update that entry's
    `last_seen`. If truly unknown, synthesize a fallback key `f"name:{name}"` so the leave is
    still recorded, and `log.warning` that no stable ID was available.

- **Every `stats_ticker()` tick (1 min)**: `update_stats_message()` already needs to call
  `rest.players()` to render the live Online field — reuse that single call to also refresh
  `online_players` (rebuild it fresh from the response each tick) and bump
  `player_history[userId]["last_seen"]` to now for everyone currently online. This self-heals
  missed join events and keeps "last seen" accurate for long play sessions (otherwise a player
  online for 3 hours would show a stale "last seen: 3 hours ago" the moment they leave, which is
  fine — but this also covers the bot-restarted-while-they-were-already-online case, where
  without this refresh they'd have no history entry until they leave).

All three call sites wrap the `rest.players()` call and history update in `try/except`,
`log.exception` and skip the update on failure — matches the existing pattern (e.g.
`get_ram_usage()`'s caller in `build_stats_embed()`) of never letting a non-critical enrichment
step break the embed or the log tailer loop.

## Embed rendering

`add_status_fields(embed, info, metrics)` becomes `add_status_fields(embed, info, metrics,
players, offline_entries)`, replacing:

```python
embed.add_field(name="Players", value=f"{metrics['currentplayernum']}/{metrics['maxplayernum']}")
```

with:

```python
online_lines = [f"**{p['name']}** — Lv.{p['level']} ({round(p['ping'])}ms)" for p in players]
embed.add_field(name="Online", value="\n".join(online_lines) if online_lines else "No one online.", inline=False)

offline_lines = [f"**{name}** — <t:{unix_ts}:R>" for name, unix_ts in offline_entries[:OFFLINE_PLAYERS_LIMIT]]
if len(offline_entries) > OFFLINE_PLAYERS_LIMIT:
    offline_lines.append(f"…and {len(offline_entries) - OFFLINE_PLAYERS_LIMIT} more")
embed.add_field(name="Offline", value="\n".join(offline_lines) if offline_lines else "None yet.", inline=False)
```

Both callers (`update_stats_message()` and the `/status` command) already call `rest.info()`
and `rest.metrics()`; both add a `rest.players()` call (already required in
`update_stats_message()` for the ticker's history refresh above; new for `/status`, which
currently doesn't fetch players).

`offline_entries` is computed as: `player_history` entries whose key isn't a value in
`online_players` (i.e. currently online), sorted by `last_seen` descending, as
`(name, unix_timestamp)` tuples.

Fields are `inline=False` since name lists can run long — keeps them stacked full-width rather
than squeezed into the existing 3-column inline layout with FPS/Uptime/Version.

## Configuration

| Var | Default | Meaning |
|---|---|---|
| `OFFLINE_PLAYERS_LIMIT` | `10` | Max offline players shown in the embed, most-recent first |

Parsed the same way as other tunables with defaults (e.g. `RAM_RESTART_COOLDOWN_MIN`):
`OFFLINE_PLAYERS_LIMIT = int(os.environ.get("OFFLINE_PLAYERS_LIMIT", "10"))`. Added to
`.env.example`.

`player_history.json` is not configurable — hardcoded relative path, added to `.gitignore`.

## Error handling

- `rest.players()` failure at any of the three update sites (join, leave, tick): caught,
  logged, that update is skipped. The embed still renders with whatever history is already in
  memory.
- Corrupt/missing `player_history.json` at startup: caught, empty dict, warning logged.
- Unresolvable leave (no stable ID, no name match in history): recorded under a synthesized
  `name:<name>` key rather than dropped, so the sighting isn't silently lost — logged as a
  warning since it indicates a missed join event.

## Non-goals / risks accepted

- Two players with the *identical* display name online at the *same time* can have their
  `online_players[name]` mapping collide (last join wins). Considered acceptable — rare, and
  Palworld doesn't prevent duplicate display names.
- Offline history grows unbounded in the JSON file over the server's lifetime (only the
  *rendered* list is capped at `OFFLINE_PLAYERS_LIMIT`, not the stored history). Acceptable —
  it's a small dict of name+timestamp strings; pruning is a possible future follow-up, not
  needed now.
- No test suite exists in this repo (per `CLAUDE.md`); verification is manual — join/leave the
  real server, confirm the embed and `player_history.json`, restart the bot to confirm history
  persists.
