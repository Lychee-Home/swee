# Release announcements in #bot-updates — design

## Problem

`release.yml` already tags and publishes a GitHub Release on every push to `main` that includes
a `feat`/`fix`/`perf` commit (see
[`2026-07-10-release-versioning-design.md`](2026-07-10-release-versioning-design.md)), but
nothing surfaces that release to players — you'd have to know to check the GitHub Releases page.
This adds an automatic, player-friendly announcement in a new `#bot-updates` text channel,
visible to the whole server. Because that channel is public, the announcement can't just be the
raw `gh release create --generate-notes` output (`fix: require BREAKING CHANGE: to start a
line...`) — it needs to read like a changelog for players, not commit history for maintainers.

## Scope

- A new `tasks.loop` in `main.py` (`release_ticker`) that polls the GitHub Releases API every 5
  minutes for the latest release on this repo.
- A humanizer that turns the auto-generated release body into a player-friendly embed: strips
  Conventional Commit prefixes and PR back-references, groups entries under "New" / "Fixes",
  and drops entry types that aren't player-relevant.
- Local state tracking the last-announced tag, so restarts don't re-announce or skip releases.
- Two new required env vars: `BOT_UPDATES_CHANNEL_ID`, `GITHUB_REPO`.

Out of scope:
- No changes to `release.yml` or how release notes are generated — it keeps producing the raw
  Conventional-Commit-based notes exactly as today; humanization happens entirely on the bot
  side when it reads the release back.
- No manual/override changelog text per PR (e.g. a "Player notes" PR body section) — auto-
  generated + humanized is enough for now. Revisit if a release's wording is regularly bad.
- No backfill of past releases — see First-run behavior below.
- No link back to the GitHub release/repo in the embed — the channel is for non-technical
  players.

## Data flow

1. `release_ticker` (new `tasks.loop(minutes=5)`, same pattern as `stats_ticker`) calls
   `GET https://api.github.com/repos/{GITHUB_REPO}/releases/latest` (unauthenticated — public
   repo, 60 req/hr limit, this uses 12/hr).
2. Compares the response's `tag_name` against the cached last-announced tag (see State below).
   If unchanged, or the request fails, do nothing this tick (failure is logged via
   `log.exception` and retried next tick — same fire-and-forget error handling as
   `update_stats_message`).
3. If a new tag is found: humanize the release `body`, build an embed, post it to
   `BOT_UPDATES_CHANNEL_ID` via the existing `broadcast_embed` helper, then update the cached
   tag.

## Humanization

`gh release create --generate-notes` produces bodies shaped like:

```
## What's Changed
* fix: require BREAKING CHANGE: to start a line, not just appear anywhere by @byroncustodio in #4
* feat: add automated semantic-version release tagging by @byroncustodio in #3

**Full Changelog**: https://github.com/owner/repo/compare/v1.1.0...v1.2.0
```

A new pure function, `humanize_release_notes(body: str) -> str | None`, parses each `* ` bullet
line with a regex matching `^(?P<type>\w+)(\(.+\))?!?: (?P<desc>.+?) by @\S+ in (#\d+|\S+)$`,
keeping only `feat` (→ "🆕 New") and `fix`/`perf` (→ "🛠️ Fixes") entries — the same set that
already gates whether a release happens at all, so there's always at least one match for a real
release. Non-matching lines (other commit types, or a body that doesn't follow the expected
shape at all — e.g. a manually created release) are dropped; each description is capitalized and
stripped of its trailing `by @user in #N`. If parsing finds zero recognized lines, the function
returns `None` and the caller falls back to posting the raw release body untouched, so a
malformed/unusual release still gets announced rather than silently skipped.

Output is plain text with a blank line between sections, e.g.:

```
🆕 New
• Add automated semantic-version release tagging

🛠️ Fixes
• Require BREAKING CHANGE: to start a line, not just appear anywhere
```

## Embed format

- Title: `🎉 {tag_name} released`
- Description: humanizer output (or raw body on fallback)
- Color: `COLOR_READY` (reused from existing palette)
- No timestamp/footer needed beyond Discord's own message timestamp.

## State

A new gitignored file, `last_release.json` (same convention as the existing gitignored
`player_history.json`), holding `{"tag": "v1.2.3"}`. Loaded at startup alongside
`load_player_history()`; written after each successful announcement.

## First-run behavior

If `last_release.json` doesn't exist when `release_ticker` first runs, it seeds the file with
whatever `releases/latest` currently returns *without posting an embed*, then returns. This
means shipping this feature doesn't dump an announcement for a release that already happened —
only releases created after the bot starts running this code get announced.

## Config additions (`.env.example`)

```
# --- Release announcements ---
BOT_UPDATES_CHANNEL_ID=123456789012345678
GITHUB_REPO=owner/repo
```

## Error handling

Consistent with the rest of the bot: GitHub API failures (rate limit, network, non-200) and
humanization edge cases are caught, logged via `log.exception`, and skipped until the next tick
— they never crash `release_ticker` or the bot process. This mirrors `stats_ticker`'s handling of
REST failures.

## Testing approach

No test runner exists in this repo (per `CLAUDE.md`). `humanize_release_notes` is a pure
function, so during implementation I'll hand-verify it against real release bodies — including
this repo's actual past releases (e.g. the v1.1.0 / v1.2.0 notes referenced above) — the same
way `compute-version-bump.sh` was hand-verified for the versioning feature. No new test
infrastructure is introduced.

## Non-goals / risks accepted

- 5-minute polling means announcements aren't instant — acceptable for a changelog notice, not a
  time-sensitive alert like the existing `ALERTS_CHANNEL_ID` messages.
- Unauthenticated GitHub API calls are subject to a 60 req/hr per-IP limit shared with anything
  else on the host hitting `api.github.com` unauthenticated; 12 req/hr from this feature leaves
  ample headroom, but if that ever becomes a problem a `GITHUB_TOKEN` could be added later for a
  higher limit.
- If `release.yml`'s generated-notes format changes (e.g. GitHub changes the default template),
  the regex may stop matching and announcements silently fall back to raw body text rather than
  erroring — acceptable since it degrades to "less pretty" rather than "broken".
