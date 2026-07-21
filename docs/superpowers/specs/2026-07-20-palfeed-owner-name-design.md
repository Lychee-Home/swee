# palfeed owner name resolution

## Summary

`palfeed`'s catch embeds (see `2026-07-20-palfeed-design.md`) currently omit who caught the pal,
since `palsave-api`'s `owner_player_uid` field (the save file's `PlayerUId` GUID) has no
counterpart in swee today — `swee/player_history.py`'s `player_history` dict is keyed by the
Palworld REST API's `userId` (`steam_XXXXXXXXXXXXXXXXX`), a different identifier for the same
player. This adds an `"Owner"` field to the catch embed when that player has been seen by the bot
before, resolved via a small addition to `player_history.py`.

Confirmed live against the deployed server (`GET /v1/api/players`) and the save's per-player file
naming, both identify the same player with the same underlying GUID, just formatted differently:

- REST API's `playerId`: `D3609521000000000000000000000000` — uppercase, no dashes, 32 hex chars
  (matches the per-player save filename, e.g. `Players/D3609521000000000000000000000000.sav`)
- `palsave-api`'s `owner_player_uid` (from `binary_reader.py`'s `guid_bytes()`): the same value
  formatted as a standard dashed GUID, e.g. `d3609521-0000-0000-0000-000000000000`

## Architecture

No new files. Two additions to `swee/player_history.py`:

- `player_history[userId]` entries gain a `"player_id"` field, storing the REST API's `playerId`
  value verbatim (uppercase, no dashes — no transformation needed at write time, since that's
  already the shape REST returns it in). Populated at the two existing call sites that already
  write `name`/`last_seen` from REST player data: `record_join()` and `refresh_online_players()`.
  Persisted automatically by the existing `save_player_history()` call already present at both
  sites — no new file, no new persistence logic.
- `resolve_owner_name(player_uid: str) -> str | None`: normalizes an incoming dashed GUID (strip
  dashes, uppercase) to match the stored `player_id` shape, then scans `player_history.values()`
  for a matching entry and returns its `name`. Returns `None` on no match (player never seen since
  `player_history.json` started tracking, or `player_uid` is `None`). A linear scan over
  `player_history` is fine — player counts are small (single/low-double digits per server), and
  this avoids maintaining a second synced index alongside the existing `userId`-keyed dict.

`swee/palfeed.py`'s `format_catch_embed` (already implemented in the current `palfeed` PR) calls
`resolve_owner_name(event["owner_player_uid"])`; if it returns a name, an `("Owner", name)` field
is appended to the embed's `fields` list alongside the existing `("Talent Score", ...)` field. If
`None`, the field is omitted entirely — consistent with how `palfeed` already handles missing data
(e.g. no `Level` field for hatched pals).

## Data flow

1. Bot already calls `record_join()` (on a player join log line) and `refresh_online_players()`
   (on `stats_ticker`, every minute) with REST player data that includes `playerId`. Both now also
   write it into `player_history[userId]["player_id"]`.
2. When `palfeed_ticker` handles a notable catch event, `format_catch_embed` calls
   `resolve_owner_name(event["owner_player_uid"])` to look up the current display name for that
   GUID, independent of whether the player is online right now.
3. Existing players in `player_history.json` from before this change won't have a `player_id`
   field until they next join or are seen by `refresh_online_players()` — `resolve_owner_name`
   treats a missing key the same as no match (`None`), no migration needed.

## Error handling

No new failure modes. `resolve_owner_name` returns `None` on no match; there's nothing to catch,
retry, or log — an unresolved owner is an expected, silent case (same as an event with no `Level`).

## Testing

`resolve_owner_name`'s normalization (dashes/case-insensitive matching) is worth a unit test.
Unlike `palfeed_notability.py` (zero-import, always testable), `player_history.py` imports
`swee.config`/`swee.rest_client`, which require a populated `.env` to import — the existing
`tests/test_releases.py` already solves this by stubbing the required env vars with
`os.environ.setdefault(...)` before importing, and the new test file should follow that same
pattern rather than inventing a different one.

## Out of scope

- No Discord-account mapping (e.g. `@mention`-ing the owner) — only the in-game display name.
- No backfill/migration of existing `player_history.json` entries; they gain `player_id` the next
  time that player is seen (join or tick refresh), same as any other field addition to this file
  has worked historically.
- No UI/embed changes beyond the one new `Owner` field on notable-catch embeds.
