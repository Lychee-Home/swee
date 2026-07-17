# Announcing missed releases (backlog catch-up) — design

## Problem

[`2026-07-10-release-announcements-design.md`](2026-07-10-release-announcements-design.md) added
`release_ticker`, which polls `GET /repos/{repo}/releases/latest` every 5 minutes and announces
the release in `#bot-updates` when its tag differs from the cached `last_release_tag`. That
endpoint only ever returns the single newest release. If two releases ship between polls (e.g.
the bot is down, or an announcement fails and isn't retried before the next release ships), the
ticker jumps straight to the newest tag and the intermediate release's changelog is never posted
— it's silently skipped with no record that it happened. This adds backlog catch-up: when the
ticker finds it's behind by more than one release, it announces all of them, oldest first.

## Scope

- Swap `fetch_latest_release()` for a list-based fetch (`GET /repos/{repo}/releases`,
  `per_page=100`, newest-first — the default GitHub ordering) so the ticker can see every release
  since the last announced one, not just the newest.
- Unlike `/releases/latest`, the `/releases` list endpoint returns drafts and prereleases too
  (drafts when authenticated with push access, prereleases always). `fetch_releases()` explicitly
  filters both out of the returned list, so this endpoint swap is a pure superset-to-catch-up
  change — the *kinds* of releases the bot can announce stay exactly as before. Decided
  deliberately after final review, not an oversight.
- `release_ticker` walks that list from the top, collecting releases until it reaches
  `last_release_tag` (or exhausts the list, e.g. on a corrupt/missing state file where seeding
  kicks in instead — see First-run behavior). It reverses the collected slice to chronological
  (oldest-first) order and announces each one in turn, same embed format as today.
- `last_release_tag` is saved after **every individual successful announcement**, not once at the
  end of the tick. If sending fails partway through a backlog, already-announced releases are
  never re-announced on retry, and the loop stops there for that tick — remaining releases retry,
  in order, on the next tick.

Out of scope:
- No cap on backlog size. However large the gap, every missed release gets its own embed. A
  pathological case (bot down for months) would post that many embeds in one tick — accepted as
  the simplest behavior; revisit only if this proves disruptive in practice.
- No pagination beyond one page of 100 releases. Realistic backlogs (a bot outage of days/weeks)
  are nowhere near 100 releases; if `last_release_tag` isn't found within the first page, all 100
  are announced and `last_release_tag` ends up as the oldest one seen; anything older stays
  un-backfilled (same as today's pre-existing limit, just moved further out).
- No changes to `humanize_release_notes`, `parse_release_header`, or the embed format — each
  missed release is humanized and posted exactly as a single release is today.
- No changes to first-run seeding behavior.
- No throttling/delay between the embeds posted within one tick — `channel.send` calls happen in
  a plain sequential loop; discord.py's client already serializes and rate-limits requests to a
  given channel under the hood.

## Data flow

1. `release_ticker` calls the new `fetch_releases_since()`-style helper, which does
   `GET /repos/{repo}/releases?per_page=100` (same auth handling as today: adds
   `Authorization: Bearer {GITHUB_TOKEN}` if set, otherwise unauthenticated).
2. If the request fails, log via `log.exception` and return — same as today, retried next tick.
3. Walk the returned list (newest-first) collecting releases whose `tag_name` != `last_release_tag`,
   stopping as soon as `last_release_tag` is found in the list (or the list is exhausted).
4. If nothing was collected (tag unchanged / list didn't move), return — no-op tick, same as today.
5. Reverse the collected slice to oldest-first order. For each release in that order:
   a. Humanize its `body` via the existing `humanize_release_notes`, falling back to raw body
      (truncated to 4000 chars) exactly as today if humanization finds nothing.
   b. Post via the existing `broadcast_embed` to `BOT_UPDATES_CHANNEL_ID`.
   c. On success, immediately `save_last_release(tag)` and continue to the next release.
   d. On failure (falsy return from `broadcast_embed`), log a warning and `break` out of the loop
      for this tick — do not skip ahead or continue posting later releases out of order.

## State

No change to `last_release.json`'s shape (`{"tag": "..."}`) or `load_last_release()`. The only
behavioral change is that `save_last_release()` is now called once per announced release within a
tick instead of at most once per tick.

## First-run behavior

Unchanged: if `last_release_tag` is `None` when `release_ticker` first runs, it seeds to whatever
the newest release currently is *without posting anything*, so shipping this feature doesn't dump
the project's entire release history into `#bot-updates` the first time it runs.

## Error handling

Consistent with the existing ticker: GitHub API failures (rate limit, network, non-200) are caught
around the fetch call, logged via `log.exception`, and the whole tick is skipped and retried next
time — unchanged from today. Within the per-release send loop, a failed `broadcast_embed` call is
logged via `log.warning` (matching today's single-release failure handling) and stops the loop
rather than raising, so the ticker itself never crashes.

## Testing approach

`tests/test_releases.py` covers the pure functions (`humanize_release_notes`,
`parse_release_header`) via `unittest`; those are untouched by this change. The new
list-walking/ordering logic lives inside `release_ticker`, which is not currently under test (it's
a `tasks.loop` coroutine that calls out to the network and Discord, same as `stats_ticker` —
neither has a test harness per `CLAUDE.md`). I'll hand-verify the walk/reverse/stop-at-last-tag
logic against constructed release lists during implementation, consistent with how
`release_ticker`'s original logic was verified.

## Non-goals / risks accepted

- No cap and no pagination beyond 100, as noted in Scope — both are pre-existing-shaped risks
  (today's code already silently loses history beyond what a single API call returns) rather than
  new ones introduced by this change.
- API cost is unchanged: still one GitHub request per 5-minute tick, just against a different
  endpoint (`/releases` instead of `/releases/latest`).
