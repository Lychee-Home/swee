# In-game `@swee` Palworld Q&A assistant

## Problem

Players in-game have no way to ask Palworld-specific questions (breeding combos, drop tables, work
suitability, etc.) without alt-tabbing to a wiki. `swee` already bridges Discord and the Palworld
server in both directions (Discord → game via `RELAY_CHANNEL_ID` forwarding, game → Discord via the
activity relay), so it's a natural place to add an in-game "ask the bot" feature backed by an LLM.

`journalctl -u $PALWORLD_SERVICE_NAME` already emits chat lines in the form:

```
[2026-07-17 05:22:41] [CHAT] <Kippei> dam they fr made a lot of the good pals like
```

`swee/log_tailer.py` currently has no regex for `[CHAT]` lines — they're read and discarded like any
other line that doesn't match `JOIN_RE`/`LEAVE_RE`/`CONNECT_RE`/`SHUTDOWN_RE`/`VERSION_RE`.

## Design

### Trigger: `@swee` chat mention

Add to `swee/log_tailer.py`:

```python
CHAT_RE = re.compile(r'\[CHAT\]\s*<(.+?)>\s*(.*)')
```

Checked in the tailer's existing `if ts_match: ... elif ...` chain, alongside `CONNECT_RE`/
`JOIN_RE`/`LEAVE_RE`. If the captured message (case-insensitively, after stripping leading
whitespace) starts with `@swee`, the rest of the message is the question. The player name comes
from the same capture group the join/leave code already uses.

Anything not matching `@swee` is chat noise the bot doesn't act on — same "read and discard" handling
as today, just via an explicit branch instead of falling through to `else`.

### Rate limiting: per-player cooldown

A module-level dict in the new `swee/assistant.py`, matching the existing in-memory-state pattern
used by `pending_connects` (`log_tailer.py`) and `online_players`/`session_started`
(`player_history.py`):

```python
_last_answered = {}  # player name -> monotonic timestamp
ASK_COOLDOWN_SEC = float(os.environ.get("ASK_COOLDOWN_SEC", "30"))
```

A question from a player within `ASK_COOLDOWN_SEC` of their last answered question is dropped
silently — no broadcast, no Discord log entry, no LLM call. This exists to cap both in-game
broadcast spam (every answer is visible to the whole server) and API cost from a player rapid-firing
questions.

### Answering: Claude + live tool lookup, no vector store

`swee/assistant.py` owns the whole answer pipeline. No embeddings, no local vector database, no
OpenAI dependency — the Palworld data needed (breeding, drops, work suitability, stats, passive
skills) is structured and keyed by pal name, so a live structured lookup is a better fit than
semantic search over a pre-built index. It also sidesteps having to keep an index in sync — the
lookup always hits current data.

**Data source**: [`palworld.wiki.gg`](https://palworld.wiki.gg), a community-maintained wiki running
MediaWiki's Cargo extension, which exposes a public, undocumented-but-functional structured query
API (`action=cargoquery`). Verified tables relevant here:

- `Pal` — base pal info (element, etc.)
- `PalStat` — base stats
- `PalWorkSuitability` — fields `palName`, `workType`, `level`
- `PalBreeding` — fields `palName`, `breedingRank`, `maleProbability`, `palEgg`
- `DropDefeat` — fields `targetName`, `itemName`, `chance`, `minQty`, `maxQty`
- `PalPassiveSkill` — passive skill data per pal

Unlike the frozen mid-2024 GitHub datasets evaluated during design (`mlg404/palworld-paldex-api`,
`blaynem/paldex`), this wiki is actively maintained (edits within days of this spec being written),
so it stays current with new content/DLC without `swee` needing its own refresh pipeline.

**Tool**: a single `lookup_pal(pal_name, aspect)` tool given to Claude, where `aspect` is one of
`breeding | drops | work_suitability | stats | passive_skills`. Implementation:

1. Fuzzy-match `pal_name` against a cached list of known pal names (fetched from the `Pal` table
   once at startup / on first use, refreshed periodically) to tolerate typos like "lambal" for
   "Lamball".
2. Issue the corresponding `cargoquery` HTTP call filtered to that pal.
3. Return the structured result (or a clear "no data found" result) to Claude.

**Model**: Claude Haiku, called with the `lookup_pal` tool available and a system prompt that:

- Instructs Claude to call `lookup_pal` for anything pal-specific (breeding/drops/work
  suitability/stats/passives) rather than guessing at exact values.
- Allows falling back to Claude's own general Palworld knowledge for broader
  strategy/mechanics questions the tool doesn't cover (e.g. "best team for a dungeon",
  general breeding mechanics) — these answers are not grounded in live data and may reflect
  Claude's training cutoff rather than the current game state, which is an accepted tradeoff
  for covering open-ended questions at all.
- Restricts scope to Palworld — off-topic questions get a short decline ("I can only help with
  Palworld questions") rather than a real answer.
- Keeps the answer short enough for a single in-game broadcast line.

### Delivery: in-game broadcast + Discord log

The answer text is sent via the existing `rest.announce()` (same REST call already used to forward
`RELAY_CHANNEL_ID` Discord messages into the game) — visible to all players, not just the asker,
since Palworld's REST API has no player-targeted message endpoint.

The question/answer pair is also posted as an embed to a new `ASSISTANT_LOG_CHANNEL_ID` channel
(`#assistant-log`), giving admins a persistent, searchable record separate from
`ALERTS_CHANNEL_ID`'s restart/settings-change traffic — useful for catching bad answers or misuse
without having to watch in-game chat.

### New configuration

Added to `.env.example` and `swee/config.py`:

- `ANTHROPIC_API_KEY` — required, no assistant functionality without it.
- `ASSISTANT_LOG_CHANNEL_ID` — required if the feature is enabled.
- `ASK_COOLDOWN_SEC` — optional, default `30`.

Following the existing optional-feature pattern (`RAM_RESTART_THRESHOLD_PCT`, `GITHUB_REPO`), the
whole feature is disabled if `ANTHROPIC_API_KEY` is unset — `@swee` mentions are then just ordinary
chat lines the tailer ignores.

### New dependency

`anthropic` (official SDK), added to `requirements.txt`.

### Error handling

- `lookup_pal`'s `cargoquery` call failing/timing out returns a tool result Claude can relay as a
  short "couldn't look that up right now" rather than raising — matching the tailer's existing
  posture of never letting one bad event kill the loop (`log_tailer()`'s outer `try/except` already
  restarts the whole subprocess on unhandled exceptions; this keeps assistant failures from
  triggering that unnecessarily).
- If the Anthropic API call itself fails, the same short in-game announcement is used; the Discord
  log entry notes the failure so an admin can investigate.

### Testing

No existing test harness covers the log-tailer/Discord command layer (per `CLAUDE.md`) — verify
manually against the live log stream: ask a real breeding/drops/work-suitability question in-game,
confirm the broadcast and the `#assistant-log` entry; ask an off-topic question and confirm the
decline; ask two questions inside the cooldown window and confirm the second is silently dropped.

## Out of scope

- No vector store / embeddings / RAG pipeline — deliberately dropped in favor of live structured
  lookups (see Design above).
- No per-player-targeted response — Palworld's REST API only supports server-wide announce, so
  every answer is a public broadcast.
- No conversation memory across questions — each `@swee` message is answered independently.
- No admin command to adjust `ASK_COOLDOWN_SEC` at runtime — it's an env var like the RAM-restart
  tuning constants, changed via `.env` + restart.
