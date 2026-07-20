# palfeed — pal-catch recap feed

## Summary

Add a new Discord feature ("palfeed") that posts notable pal catches to a dedicated channel, by
polling a companion service — `palsave-api` (separate repo, see
`docs/superpowers/specs/2026-07-20-palsave-api-design.md` in that repo once it exists) — for
newly-acquired-pal events. `palsave-api` owns everything CPU/IO-heavy (Palworld save decompression,
Gvas parsing, backup-folder watching, structural diffing); swee only ever sees small JSON event
records over HTTP. This supersedes an earlier version of this spec that planned to port the
decompress/parse/diff logic directly into `swee` — that approach was dropped because the work is
CPU-bound enough to contend with discord.py's event loop, and because the parsing logic is
independently reusable (a future website consumer), which argues for a standalone service rather
than bot-embedded code.

## Architecture

One new module, following the existing one-module-per-concern convention:

- `swee/palfeed.py` — `palfeed_ticker`: polls `palsave-api`'s `GET /events/new-pals` endpoint,
  applies notability rules locally, and posts notable catches via `broadcast_embed`. Also owns
  `notability_tier()` and the talent-tier constants (ported from palsave's `recap.py`) — this is
  the one piece of the original recap logic that stays in swee, since deciding what's "worth
  announcing in a Discord highlight channel" is a bot-product decision, not a save-parsing fact.

No decompression, Gvas parsing, ctypes, or `libooz.so` in swee at all — that entire surface moves
to `palsave-api`.

## Configuration

New env vars, following existing `.env.example` conventions:

```
# --- Pal catch recap feed (optional) ---
# Base URL of the palsave-api service (see that repo). Leave unset/blank to disable palfeed
# entirely — same opt-in pattern as GITHUB_REPO gating release_ticker.
PALFEED_SERVICE_URL=http://127.0.0.1:8787
PALFEED_CHANNEL_ID=123456789012345678
```

`PALFEED_CHANNEL_ID` is a new dedicated channel (not reused from `ACTIVITY_CHANNEL_ID`) so pal
catch highlights stay separable from player join/leave activity.

Poll interval is fixed at 60s (matches `stats_ticker`'s cadence) — no separate interval env var.

## Data flow

1. `@tasks.loop(seconds=60) palfeed_ticker()`, started in `on_ready` alongside `stats_ticker`/
   `release_ticker`, gated on `PALFEED_SERVICE_URL` being set.
2. Each tick: `GET {PALFEED_SERVICE_URL}/events/new-pals?since=<cursor>&limit=5`. `limit=5` both
   bounds normal-tick work and throttles catch-up after downtime — if the bot was offline and a
   backlog piled up, it drains 5 events per tick across consecutive ticks instead of flooding the
   channel with everything at once.
3. For each event in the response (oldest first): compute `notability_tier()`; if notable, post
   via `broadcast_embed(...)` targeting `PALFEED_CHANNEL_ID`. Non-notable events are skipped but
   still count toward cursor advancement (they don't get re-fetched next tick).
4. Cursor (`last_event_id`) advances to an event's `id` immediately after it's fully handled
   (posted, or skipped as non-notable), persisted to `palfeed_state.json` (sibling of the existing
   `last_release.json` pattern in `releases.py`). On a Discord send failure, stop processing the
   batch and leave the cursor at the last successfully handled event — same `break`-on-failure
   pattern `release_ticker` already uses — so it retries from exactly that point next tick rather
   than skipping or duplicating.
5. First run (no cached cursor): start from whatever the service returns for `since=0` — no
   special-casing needed on swee's side, since `palsave-api` already handles "don't replay all of
   history" on its own first run.

## Notability rules (ported from palsave's recap.py, swee-owned)

- Instant qualifiers: `is_rare_pal` → "Lucky", `is_awakening` → "Awakened".
- Otherwise, talent score (`talent_hp + talent_shot + talent_defense`, max 300) tiers: 300
  "Perfect", 280+ "Excellent", 250+ "Great". Calibrated against one reference save's own
  distribution, not a verified community standard.
- Acquisition type, recruitable-NPC exclusion, and the wild/purchased/hatched classification
  itself are `palsave-api`'s responsibility (structural facts about the save), not swee's — swee
  only receives the already-classified `acquisition_type` field and uses it for embed formatting.

## Error handling

- HTTP request failures (service unreachable, non-2xx, timeout): log and skip the tick; cursor
  untouched, retried next tick.
- Broadcast failures: `broadcast_embed` already catches and logs internally and returns `None`;
  palfeed stops advancing the cursor at that point (see Data flow step 4) rather than blocking the
  whole tick indefinitely.

## Testing

`notability_tier()` is a pure function — worth a unit test mirroring
`tests/test_palworld_settings.py`'s style. No coverage of the Discord command/HTTP-polling layer
itself, consistent with the rest of the bot's command layer today.

## Out of scope

- No decompression, Gvas parsing, or `libooz.so` vendoring in swee — lives in `palsave-api`.
- No changes to the `palsave` sandbox repo — left as-is.
- No CLI entry points.
- `palsave-api` itself is designed separately (`2026-07-20-palsave-api-design.md`, to live in its
  own repo) — this spec only covers swee's consumer side.
