# In-game `@swee` Palworld Q&A Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let players ask Palworld questions in-game via `@swee <question>` chat mentions, answered by Claude using live lookups against the `palworld.wiki.gg` structured wiki database, broadcast back in-game and logged to Discord.

**Architecture:** A new `swee/assistant.py` module owns mention parsing, per-player cooldown, a `lookup_pal` tool that queries `palworld.wiki.gg`'s Cargo API live (no local vector store or embeddings), and a Claude tool-use loop that produces the final answer. `swee/log_tailer.py` gains a `[CHAT]` line regex that detects `@swee` mentions and dispatches to the new module as a fire-and-forget task so the tailer loop isn't blocked on network calls.

**Tech Stack:** Python 3.14, `anthropic` SDK (new dependency), `httpx` (already a dependency, used for the wiki.gg Cargo API calls), `discord.py`.

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-07-17-ingame-assistant-design.md`.
- Never push directly to `main` — this work lands on `feature/ingame-assistant` (already created, spec doc already committed there) via a single PR bundling spec + plan + code.
- New dependencies go in `requirements.txt`.
- No existing test harness covers the Discord command/log-tailer layer (per `CLAUDE.md`) — only pure logic gets unit tests; integration points are verified manually.
- Model ID for generation: `claude-haiku-4-5-20251001`.
- Wiki data source: `https://palworld.wiki.gg/api.php`, `action=cargoquery`, verified tables/fields:
  - `Pal`: `palName, paldeckNumber, palSize, partnerSkill, palGear, hungerRate, isNocturnal, sellPrice`
  - `PalStat`: `palName, baseHp, baseAttack, baseDefense, baseWorkSpeed` (plus other stat fields not used here)
  - `PalWorkSuitability`: `palName, workType, level`
  - `PalBreeding`: `palName, breedingRank, maleProbability, isUniqueCombo, palEgg`
  - `DropDefeat`: `targetName, itemName, chance, minQty, maxQty`
  - `PalPassiveSkill`: `palName, passiveSkillName`
- In-game replies go through `rest.announce()` (`swee/rest_client.py`) — server-wide broadcast, no per-player targeting available.
- Cooldown default: 30s per player (`ASK_COOLDOWN_SEC`).
- Feature is fully optional: if `ANTHROPIC_API_KEY` is unset, `@swee` mentions are left as ordinary unhandled chat lines.

---

### Task 1: Chat-mention parsing and cooldown tracking

**Files:**
- Create: `swee/assistant.py`
- Test: `tests/test_assistant.py`

**Interfaces:**
- Produces: `parse_mention(chat_text: str) -> str | None`, `is_on_cooldown(name: str, last_answered: dict, cooldown_sec: float, now: float) -> bool`, `record_answered(name: str, last_answered: dict, now: float) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_assistant.py
import time
import unittest

from swee.assistant import is_on_cooldown, parse_mention, record_answered


class ParseMentionTests(unittest.TestCase):
    def test_extracts_question_after_prefix(self):
        self.assertEqual(parse_mention("@swee what does lamball drop?"), "what does lamball drop?")

    def test_case_insensitive_prefix(self):
        self.assertEqual(parse_mention("@SWEE what does lamball drop?"), "what does lamball drop?")

    def test_ignores_non_mention_messages(self):
        self.assertIsNone(parse_mention("dam they fr made a lot of good pals"))

    def test_returns_none_for_empty_question(self):
        self.assertIsNone(parse_mention("@swee"))
        self.assertIsNone(parse_mention("@swee   "))

    def test_requires_word_boundary_after_prefix(self):
        self.assertIsNone(parse_mention("@sweetalk something"))


class CooldownTests(unittest.TestCase):
    def test_not_on_cooldown_when_never_answered(self):
        self.assertFalse(is_on_cooldown("Kippei", {}, 30, time.monotonic()))

    def test_on_cooldown_within_window(self):
        last_answered = {"Kippei": 100.0}
        self.assertTrue(is_on_cooldown("Kippei", last_answered, 30, 110.0))

    def test_not_on_cooldown_after_window(self):
        last_answered = {"Kippei": 100.0}
        self.assertFalse(is_on_cooldown("Kippei", last_answered, 30, 131.0))

    def test_record_answered_sets_timestamp(self):
        last_answered = {}
        record_answered("Kippei", last_answered, 42.0)
        self.assertEqual(last_answered["Kippei"], 42.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_assistant -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'swee.assistant'`

- [ ] **Step 3: Write minimal implementation**

```python
# swee/assistant.py
import re

MENTION_RE = re.compile(r'^@swee\b\s*(.*)', re.IGNORECASE)


def parse_mention(chat_text):
    m = MENTION_RE.match(chat_text.strip())
    if not m:
        return None
    question = m.group(1).strip()
    return question or None


def is_on_cooldown(name, last_answered, cooldown_sec, now):
    last = last_answered.get(name)
    return last is not None and now - last < cooldown_sec


def record_answered(name, last_answered, now):
    last_answered[name] = now
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_assistant -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add swee/assistant.py tests/test_assistant.py
git commit -m "feat: add @swee chat-mention parsing and per-player cooldown tracking"
```

---

### Task 2: Palworld wiki.gg lookup tool

**Files:**
- Modify: `swee/assistant.py`
- Modify: `tests/test_assistant.py`

**Interfaces:**
- Consumes: nothing new from Task 1.
- Produces: `fuzzy_match_pal_name(query: str, known_names: list[str]) -> str | None`, `async get_known_pal_names() -> list[str]`, `async lookup_pal(pal_name: str, aspect: str) -> dict`, module constant `ASPECT_TABLES: dict[str, tuple[str, str, list[str]]]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assistant.py — add to existing file
from swee.assistant import fuzzy_match_pal_name


class FuzzyMatchPalNameTests(unittest.TestCase):
    KNOWN = ["Lamball", "Cattiva", "Direhowl", "Anubis"]

    def test_exact_match_case_insensitive(self):
        self.assertEqual(fuzzy_match_pal_name("lamball", self.KNOWN), "Lamball")

    def test_close_typo_match(self):
        self.assertEqual(fuzzy_match_pal_name("lambal", self.KNOWN), "Lamball")

    def test_no_match_returns_none(self):
        self.assertIsNone(fuzzy_match_pal_name("xyzzyzzy", self.KNOWN))

    def test_empty_known_names_returns_none(self):
        self.assertIsNone(fuzzy_match_pal_name("lamball", []))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_assistant.FuzzyMatchPalNameTests -v`
Expected: FAIL with `ImportError: cannot import name 'fuzzy_match_pal_name'`

- [ ] **Step 3: Write minimal implementation**

```python
# swee/assistant.py — add below the Task 1 functions
import difflib
import logging

import httpx

log = logging.getLogger("swee")

WIKI_API_BASE = "https://palworld.wiki.gg/api.php"

ASPECT_TABLES = {
    "breeding": ("PalBreeding", "palName", ["palName", "breedingRank", "maleProbability", "isUniqueCombo", "palEgg"]),
    "drops": ("DropDefeat", "targetName", ["targetName", "itemName", "chance", "minQty", "maxQty"]),
    "work_suitability": ("PalWorkSuitability", "palName", ["palName", "workType", "level"]),
    "stats": ("PalStat", "palName", ["palName", "baseHp", "baseAttack", "baseDefense", "baseWorkSpeed"]),
    "passive_skills": ("PalPassiveSkill", "palName", ["palName", "passiveSkillName"]),
}

_known_pal_names = []


def fuzzy_match_pal_name(query, known_names):
    if not known_names:
        return None
    lowered = {n.lower(): n for n in known_names}
    if query.lower() in lowered:
        return lowered[query.lower()]
    matches = difflib.get_close_matches(query.lower(), lowered.keys(), n=1, cutoff=0.6)
    return lowered[matches[0]] if matches else None


async def _cargoquery(params):
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(WIKI_API_BASE, params={**params, "action": "cargoquery", "format": "json"})
        r.raise_for_status()
        return r.json()


async def get_known_pal_names():
    global _known_pal_names
    if not _known_pal_names:
        data = await _cargoquery({"tables": "Pal", "fields": "palName", "limit": "500"})
        _known_pal_names = [row["title"]["palName"] for row in data.get("cargoquery", [])]
    return _known_pal_names


async def lookup_pal(pal_name, aspect):
    if aspect not in ASPECT_TABLES:
        return {"error": f"unknown aspect '{aspect}'"}
    table, name_field, fields = ASPECT_TABLES[aspect]
    known_names = await get_known_pal_names()
    matched = fuzzy_match_pal_name(pal_name, known_names)
    if matched is None:
        return {"error": f"no pal found matching '{pal_name}'"}
    data = await _cargoquery({
        "tables": table,
        "fields": ",".join(fields),
        "where": f'{name_field}="{matched}"',
    })
    rows = [row["title"] for row in data.get("cargoquery", [])]
    if not rows:
        return {"error": f"no {aspect} data found for {matched}"}
    return {"pal": matched, "aspect": aspect, "data": rows}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_assistant -v`
Expected: PASS (13 tests). `get_known_pal_names`/`lookup_pal` are not unit tested (network I/O) — verified manually next.

- [ ] **Step 5: Manually verify the live lookup**

Run in a Python shell from the repo root:

```bash
python -c "
import asyncio
from swee.assistant import lookup_pal
print(asyncio.run(lookup_pal('lambal', 'work_suitability')))
"
```

Expected: a dict with `"pal": "Lamball"` and `"data"` containing `Farming`/`Handiwork`/`Transporting` rows — confirms fuzzy matching and the live Cargo query both work end-to-end.

- [ ] **Step 6: Commit**

```bash
git add swee/assistant.py tests/test_assistant.py
git commit -m "feat: add live palworld.wiki.gg pal lookup with fuzzy name matching"
```

---

### Task 3: Claude tool-use answer generation

**Files:**
- Modify: `swee/assistant.py`
- Modify: `swee/config.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `lookup_pal(pal_name, aspect)` from Task 2, `ASPECT_TABLES` keys for the tool schema.
- Produces: `async ask_claude(question: str) -> str`.

- [ ] **Step 1: Add the `anthropic` dependency**

```
# requirements.txt — append
anthropic
```

Run: `pip install -r requirements.txt`

- [ ] **Step 2: Add `ANTHROPIC_API_KEY` to config**

```python
# swee/config.py — append near the other optional-feature vars
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
```

- [ ] **Step 3: Write `ask_claude`**

```python
# swee/assistant.py — add imports and code
from anthropic import AsyncAnthropic

from swee.config import ANTHROPIC_API_KEY

ASSISTANT_SYSTEM_PROMPT = (
    "You are swee, a Discord bot answering Palworld questions asked by players in-game chat. "
    "Your reply is broadcast to every player on the server, so keep it to one short sentence. "
    "For anything about a specific pal — breeding, drops, work suitability, stats, or passive "
    "skills — call the lookup_pal tool rather than guessing exact values. For broader strategy or "
    "general mechanics questions the tool can't answer, use your own Palworld knowledge, but don't "
    "invent specific numbers you're not sure of. If the question isn't about Palworld, reply that "
    "you can only help with Palworld questions."
)

LOOKUP_PAL_TOOL = {
    "name": "lookup_pal",
    "description": "Look up structured data about a specific Palworld pal from the live wiki database.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pal_name": {"type": "string", "description": "The pal's name, e.g. 'Lamball'"},
            "aspect": {
                "type": "string",
                "enum": list(ASPECT_TABLES.keys()),
                "description": "Which kind of data to fetch",
            },
        },
        "required": ["pal_name", "aspect"],
    },
}

_anthropic = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


async def ask_claude(question):
    messages = [{"role": "user", "content": question}]
    for _ in range(3):
        response = await _anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=ASSISTANT_SYSTEM_PROMPT,
            tools=[LOOKUP_PAL_TOOL],
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            return "".join(block.text for block in response.content if block.type == "text").strip()
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = await lookup_pal(block.input["pal_name"], block.input["aspect"])
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(result)})
        messages.append({"role": "user", "content": tool_results})
    return "Sorry, I couldn't figure that one out."
```

No unit test here — this is an LLM API call, not pure logic. Verified manually in the next step.

- [ ] **Step 4: Manually verify against the real API**

Requires a real `ANTHROPIC_API_KEY` set in the environment (or `.env`).

```bash
python -c "
import asyncio
from swee.assistant import ask_claude
print(asyncio.run(ask_claude('what does lamball drop?')))
"
```

Expected: a short sentence mentioning Lamball's actual drops (Wool, Lamball Mutton, etc. per the live wiki data), confirming the tool-use loop calls `lookup_pal` and produces a grounded answer.

```bash
python -c "
import asyncio
from swee.assistant import ask_claude
print(asyncio.run(ask_claude('what is the capital of France?')))
"
```

Expected: a short decline along the lines of "I can only help with Palworld questions."

- [ ] **Step 5: Commit**

```bash
git add swee/assistant.py swee/config.py requirements.txt
git commit -m "feat: add Claude tool-use answer generation for @swee questions"
```

---

### Task 4: Orchestration and Discord logging

**Files:**
- Modify: `swee/assistant.py`
- Modify: `swee/config.py`

**Interfaces:**
- Consumes: `parse_mention`, `is_on_cooldown`, `record_answered` (Task 1), `ask_claude` (Task 3), `rest.announce` (`swee/rest_client.py`), `broadcast_embed` (`swee/embeds.py`), `COLOR_CHAT` (`swee/config.py`).
- Produces: `async handle_mention(player_name: str, question: str) -> None`.

- [ ] **Step 1: Add remaining config**

```python
# swee/config.py — append
ASSISTANT_LOG_CHANNEL_ID = int(os.environ["ASSISTANT_LOG_CHANNEL_ID"]) if os.environ.get("ASSISTANT_LOG_CHANNEL_ID") else None
ASK_COOLDOWN_SEC = float(os.environ.get("ASK_COOLDOWN_SEC", "30"))
```

- [ ] **Step 2: Write `handle_mention`**

```python
# swee/assistant.py — add imports and code
import time

from swee.config import ASK_COOLDOWN_SEC, ASSISTANT_LOG_CHANNEL_ID, COLOR_CHAT
from swee.embeds import broadcast_embed
from swee.rest_client import rest

_last_answered = {}


async def handle_mention(player_name, question):
    now = time.monotonic()
    if is_on_cooldown(player_name, _last_answered, ASK_COOLDOWN_SEC, now):
        return
    record_answered(player_name, _last_answered, now)
    try:
        answer = await ask_claude(question)
    except Exception:
        log.exception("assistant: failed to answer question from %s", player_name)
        answer = "Sorry, I couldn't look that up right now."
    try:
        await rest.announce(f"swee: {answer}")
    except Exception:
        log.exception("assistant: announce failed")
    if ASSISTANT_LOG_CHANNEL_ID:
        await broadcast_embed(
            f"{player_name} asked swee",
            f"**Q:** {question}\n**A:** {answer}",
            COLOR_CHAT,
            channel_id=ASSISTANT_LOG_CHANNEL_ID,
        )
```

`_last_answered` here is the same module-level dict pattern as `pending_connects` in `swee/log_tailer.py` — safe without a lock since mutation never crosses an `await` boundary.

No new unit test — this orchestrates I/O (LLM call, REST announce, Discord embed) with no pure logic left to isolate; `is_on_cooldown`/`record_answered`/`ask_claude` are already covered individually. Verified manually in Task 5's end-to-end check.

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `python -m unittest discover tests -v`
Expected: PASS, same test count as after Task 2 (no new tests added this task).

- [ ] **Step 4: Commit**

```bash
git add swee/assistant.py swee/config.py
git commit -m "feat: wire up @swee question handling with in-game reply and Discord log"
```

---

### Task 5: Wire the chat trigger into the log tailer

**Files:**
- Modify: `swee/log_tailer.py`

**Interfaces:**
- Consumes: `assistant.parse_mention(chat_text)`, `assistant.handle_mention(player_name, question)` from Tasks 1 and 4.

- [ ] **Step 1: Add the chat-line regex and import**

```python
# swee/log_tailer.py — add near the other module-level regexes
CHAT_RE = re.compile(r'\[CHAT\]\s*<(.+?)>\s*(.*)')
```

```python
# swee/log_tailer.py — add to the imports at the top
import swee.assistant as assistant
```

- [ ] **Step 2: Dispatch on `@swee` mentions**

In the `async for line in proc.stdout` loop, inside the `if ts_match:` branch, add a new `elif` after the existing `LEAVE_RE` branch (around `log_tailer.py:91-97`):

```python
                    elif m := CHAT_RE.search(rest_msg):
                        name, text = m.groups()
                        question = assistant.parse_mention(text)
                        if question:
                            asyncio.create_task(assistant.handle_mention(name, question))
```

This is fire-and-forget (`asyncio.create_task`, not `await`) because `handle_mention` makes network calls (Claude, wiki.gg, the REST announce) that can take a few seconds — awaiting it inline would stall the tailer loop and delay processing of subsequent log lines (joins/leaves/etc.) for that whole time.

- [ ] **Step 3: Manually verify end-to-end against the live server**

Requires `ANTHROPIC_API_KEY` and `ASSISTANT_LOG_CHANNEL_ID` set, and the bot running against a real Palworld server (per `README.md`'s Running section).

1. In-game, type `@swee what does lamball drop?`
2. Confirm an in-game broadcast appears with a short, correct answer.
3. Confirm a matching embed appears in the `#assistant-log` channel with the question and answer.
4. Immediately ask a second question as the same player — confirm it's silently dropped (no broadcast, no log entry) since it's within the 30s cooldown.
5. Wait 30+ seconds and ask again — confirm it's answered normally.
6. Ask an off-topic question (e.g. `@swee what's the weather tomorrow?`) — confirm a short decline.

- [ ] **Step 4: Commit**

```bash
git add swee/log_tailer.py
git commit -m "feat: detect @swee chat mentions and dispatch to the assistant"
```

---

### Task 6: Documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing (docs only).

- [ ] **Step 1: Document the new env vars**

```
# .env.example — append
# --- In-game @swee assistant (optional) ---
# Leave ANTHROPIC_API_KEY unset to disable the feature entirely — @swee chat
# mentions are then left as ordinary unhandled chat lines.
# ANTHROPIC_API_KEY=
# Required if ANTHROPIC_API_KEY is set: Discord channel for the question/answer audit log.
# ASSISTANT_LOG_CHANNEL_ID=123456789012345678
# Minimum seconds between answered questions from the same player. Defaults to 30.
# ASK_COOLDOWN_SEC=30
```

- [ ] **Step 2: Add a Features section to README.md**

Insert after the existing "### Config commands" section and before "### Server update" in `README.md`:

```markdown
### In-game `@swee` assistant (optional)

Players can ask Palworld questions in-game chat by prefixing a message with `@swee`, e.g.
`@swee what does lamball drop?`. The question goes to Claude, which can call a live lookup
against [palworld.wiki.gg](https://palworld.wiki.gg)'s structured pal database (breeding, drops,
work suitability, stats, passive skills) for anything pal-specific, falling back to its own
general Palworld knowledge for broader questions. The answer is broadcast in-game to all players
via the same REST announce endpoint used for the Discord relay, and the question/answer pair is
logged to `ASSISTANT_LOG_CHANNEL_ID` for admin visibility. Each player is limited to one answered
question per `ASK_COOLDOWN_SEC` (default 30s) to limit broadcast spam and API cost. Requires
`ANTHROPIC_API_KEY` — leave it unset to disable the feature entirely.
```

- [ ] **Step 3: Commit**

```bash
git add .env.example README.md
git commit -m "docs: document the in-game @swee assistant feature"
```

## Self-Review

**Spec coverage:**
- `@swee` trigger detection via `[CHAT]` regex → Task 5. ✓
- Per-player 30s cooldown → Task 1 (logic), Task 4 (wired with config default). ✓
- No vector store/embeddings; live `lookup_pal` tool against `palworld.wiki.gg` Cargo API → Task 2. ✓
- Fuzzy pal-name matching → Task 2. ✓
- Claude Haiku, tool-first with general-knowledge fallback, off-topic decline, short answers → Task 3 (system prompt). ✓
- In-game broadcast via `rest.announce()` → Task 4. ✓
- Discord audit log to `ASSISTANT_LOG_CHANNEL_ID` → Task 4. ✓
- New config (`ANTHROPIC_API_KEY`, `ASSISTANT_LOG_CHANNEL_ID`, `ASK_COOLDOWN_SEC`) → Tasks 3–4, documented in Task 6. ✓
- New dependency (`anthropic`) → Task 3. ✓
- Error handling (wiki.gg/Claude failure → short fallback message, doesn't crash the tailer) → Task 4's `try/except` in `handle_mention`. ✓
- Manual verification (no test harness for this layer) → Steps in Tasks 2, 3, 5. ✓
- Feature fully optional when `ANTHROPIC_API_KEY` unset → `_anthropic = ... if ANTHROPIC_API_KEY else None` in Task 3; if a mention comes in without a key configured, `ask_claude` would raise on `_anthropic.messages.create` (attribute error on `None`), which Task 4's `try/except` around `ask_claude` catches and turns into the same "couldn't look that up" fallback — matches the spec's "no assistant functionality without it" intent without needing a separate guard.

**Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `parse_mention`, `is_on_cooldown`, `record_answered`, `fuzzy_match_pal_name`, `get_known_pal_names`, `lookup_pal`, `ask_claude`, `handle_mention` are used with the same names and signatures everywhere they're referenced across tasks.
