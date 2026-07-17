# Per-Player Conversation Sessions for @swee Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `@swee` remember a player's prior questions/answers within their current play session, so follow-up questions ("what about its passive skills?") have context, without mixing up players who share a display name or persisting anything across a player's logout.

**Architecture:** A new in-memory session store in `swee/assistant.py`, keyed by the player's stable REST `userId` (resolved via `swee/player_history.py`'s existing `online_players` map, not display name), capped at 8 exchanges per player, cleared when the player leaves the server (hooking into `swee/log_tailer.py`'s existing leave-detection).

**Tech Stack:** Python 3.14, no new dependencies.

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-07-17-assistant-session-memory-design.md`.
- Sessions are keyed by player `userId` (resolved from `swee/player_history.py`'s `online_players` dict, name → `userId`), falling back to display name if not yet resolved. The existing per-player cooldown (`_last_answered`) is also re-keyed to `userId` for the same reason.
- Session history stores simplified `{"role": "user"|"assistant", "content": str}` text pairs only — never the raw Anthropic tool-use/tool-result blocks from a question's internal tool loop.
- Cap: 8 exchanges (16 messages) per player, oldest dropped first.
- Sessions are in-memory only (module-level dict), no persistence across bot restarts — matches every other session-scoped dict in this codebase.
- Sessions clear on player logout only — no inactivity timeout.
- No new module: `swee/assistant.py` imports `online_players` directly from `swee/player_history.py`, matching `swee/commands.py`'s existing precedent of importing the same dict.
- A failed/fallback answer (exception during `ask_claude`) is never saved into a player's session.
- Never push directly to `main` — this work lands on `feature/assistant-session-memory` (spec already committed there) via one PR bundling spec + plan + code.
- No existing test harness covers the Discord command/log-tailer layer (per `CLAUDE.md`) — only pure logic gets unit tests; `ask_claude`'s history-passing and the full `handle_mention`/log-tailer wiring are verified manually.

---

### Task 1: Player id resolution and session pop/clear primitives

**Files:**
- Modify: `swee/assistant.py`
- Modify: `tests/test_assistant.py`

**Interfaces:**
- Produces: `resolve_player_id(name: str, online_players: dict) -> str`, `pop_session(player_id: str, sessions: dict) -> None`, `clear_session(player_id: str) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_assistant.py — add to existing file
from swee.assistant import clear_session, pop_session, resolve_player_id


class ResolvePlayerIdTests(unittest.TestCase):
    def test_returns_userid_when_known(self):
        self.assertEqual(resolve_player_id("Kippei", {"Kippei": "steam_123"}), "steam_123")

    def test_falls_back_to_name_when_unknown(self):
        self.assertEqual(resolve_player_id("Kippei", {}), "Kippei")


class PopSessionTests(unittest.TestCase):
    def test_removes_existing_session(self):
        sessions = {"steam_123": [{"role": "user", "content": "hi"}]}
        pop_session("steam_123", sessions)
        self.assertNotIn("steam_123", sessions)

    def test_noop_for_missing_session(self):
        sessions = {}
        pop_session("steam_123", sessions)
        self.assertEqual(sessions, {})


class ClearSessionTests(unittest.TestCase):
    def test_clears_module_level_session_store(self):
        import swee.assistant as assistant_module
        assistant_module._sessions["steam_123"] = [{"role": "user", "content": "hi"}]
        clear_session("steam_123")
        self.assertNotIn("steam_123", assistant_module._sessions)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_assistant -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_player_id'`

- [ ] **Step 3: Write minimal implementation**

Add to `swee/assistant.py`, near the existing `is_on_cooldown`/`record_answered` functions (around line 38-44):

```python
def resolve_player_id(name, online_players):
    return online_players.get(name, name)


def pop_session(player_id, sessions):
    sessions.pop(player_id, None)
```

Add near the bottom of the file, after `_last_answered = {}` (currently line 148), a new session store and the public clear wrapper:

```python
_sessions = {}  # player id -> list of {"role", "content"} pairs, capped at 16 (8 exchanges)


def clear_session(player_id):
    pop_session(player_id, _sessions)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_assistant -v`
Expected: PASS (all previous tests plus 5 new ones)

- [ ] **Step 5: Commit**

```bash
git add swee/assistant.py tests/test_assistant.py
git commit -m "feat: add player id resolution and session clear primitives"
```

---

### Task 2: Session append/trim and ask_claude history parameter

**Files:**
- Modify: `swee/assistant.py`
- Modify: `tests/test_assistant.py`

**Interfaces:**
- Consumes: nothing new from Task 1 directly (independent pure logic), but lands in the same module.
- Produces: `append_exchange(player_id: str, sessions: dict, question: str, answer: str, limit: int) -> None`, `ask_claude(question: str, history: list | None = None) -> str` (signature change — `history` param added).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assistant.py — add to existing file
from swee.assistant import append_exchange


class AppendExchangeTests(unittest.TestCase):
    def test_appends_question_and_answer(self):
        sessions = {}
        append_exchange("steam_123", sessions, "what does lamball drop?", "Wool and Lamball Mutton.", 8)
        self.assertEqual(sessions["steam_123"], [
            {"role": "user", "content": "what does lamball drop?"},
            {"role": "assistant", "content": "Wool and Lamball Mutton."},
        ])

    def test_trims_to_limit_exchanges(self):
        sessions = {"steam_123": []}
        for i in range(10):
            append_exchange("steam_123", sessions, f"q{i}", f"a{i}", 3)
        self.assertEqual(len(sessions["steam_123"]), 6)
        self.assertEqual(sessions["steam_123"][0], {"role": "user", "content": "q7"})
        self.assertEqual(sessions["steam_123"][-1], {"role": "assistant", "content": "a9"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_assistant.AppendExchangeTests -v`
Expected: FAIL with `ImportError: cannot import name 'append_exchange'`

- [ ] **Step 3: Write minimal implementation**

Add to `swee/assistant.py`, next to `pop_session` (from Task 1):

```python
def append_exchange(player_id, sessions, question, answer, limit):
    history = sessions.get(player_id, [])
    history = history + [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    sessions[player_id] = history[-(limit * 2):]
```

Add the cap constant near `_sessions = {}` (from Task 1):

```python
SESSION_HISTORY_LIMIT = 8
```

Modify `ask_claude` (currently `swee/assistant.py:124`) to accept and prepend history:

```python
async def ask_claude(question, history=None):
    messages = list(history or []) + [{"role": "user", "content": question}]
    for _ in range(3):
        response = await _anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=ASSISTANT_SYSTEM_PROMPT,
            tools=[LOOKUP_PAL_TOOL],
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            text = "".join(block.text for block in response.content if block.type == "text").strip()
            return text or "Sorry, I couldn't figure that one out."
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = await lookup_pal(block.input["pal_name"], block.input["aspect"])
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)})
        messages.append({"role": "user", "content": tool_results})
    return "Sorry, I couldn't figure that one out."
```

(Only the first line of the function body changes — `messages = [{"role": "user", "content": question}]` becomes `messages = list(history or []) + [{"role": "user", "content": question}]`. Everything else is unchanged from the current implementation.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover tests -v`
Expected: PASS, all existing tests plus the 2 new `AppendExchangeTests`. `ask_claude` itself has no new unit test (network/LLM call, not unit tested in this repo) — its `history` behavior is verified manually in Task 3.

- [ ] **Step 5: Commit**

```bash
git add swee/assistant.py tests/test_assistant.py
git commit -m "feat: add session append/trim and ask_claude history parameter"
```

---

### Task 3: Wire sessions into handle_mention

**Files:**
- Modify: `swee/assistant.py`

**Interfaces:**
- Consumes: `resolve_player_id`, `append_exchange` (Task 1/2), `is_on_cooldown`, `record_answered` (pre-existing), `ask_claude(question, history=None)` (Task 2), `online_players` from `swee/player_history.py`.
- Produces: updated `handle_mention(player_name: str, question: str) -> None` (same signature, new internal behavior).

- [ ] **Step 1: Add the import**

```python
# swee/assistant.py — add to imports at the top
from swee.player_history import online_players
```

- [ ] **Step 2: Rewrite handle_mention**

Replace the current `handle_mention` (currently `swee/assistant.py:151-174`) with:

```python
async def handle_mention(player_name, question):
    if _anthropic is None:
        return
    player_id = resolve_player_id(player_name, online_players)
    now = time.monotonic()
    if is_on_cooldown(player_id, _last_answered, ASK_COOLDOWN_SEC, now):
        return
    record_answered(player_id, _last_answered, now)
    history = _sessions.get(player_id, [])
    try:
        answer = await ask_claude(question, history)
        append_exchange(player_id, _sessions, question, answer, SESSION_HISTORY_LIMIT)
    except Exception:
        log.exception("assistant: failed to answer question from %s", player_name)
        answer = "Sorry, I couldn't look that up right now."
    try:
        await rest.announce(f"[swee] {answer}")
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

Note the cooldown check/record and session lookup all use `player_id`, not `player_name` — the broadcast and Discord log embed still use `player_name` for readability. `append_exchange` is called only inside the `try` block, right after a successful `ask_claude` call, so a fallback/error `answer` from the `except` branch is never saved into the session.

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `python -m unittest discover tests -v`
Expected: PASS, same test count as after Task 2 (no new tests this task — `handle_mention` is I/O orchestration, verified manually below, matching how it was already handled in the original assistant feature's plan).

- [ ] **Step 4: Manually verify with a real API key**

Requires `ANTHROPIC_API_KEY` set (and ideally a way to simulate `online_players` — if no live Palworld server is available, this step can be deferred to deploy verification like the original assistant feature's live-API checks were).

```bash
python -c "
import asyncio
from swee.assistant import handle_mention, _sessions
asyncio.run(handle_mention('TestPlayer', 'what does lamball drop?'))
asyncio.run(handle_mention('TestPlayer', 'what about its work suitability?'))
print(_sessions)
"
```

Expected: the second call's answer references Lamball specifically (inferred from session context) even though the second question never named a pal, and `_sessions` shows an entry (keyed by `'TestPlayer'`, since no `online_players` entry exists in this standalone script) with 4 messages (2 exchanges).

- [ ] **Step 5: Commit**

```bash
git add swee/assistant.py
git commit -m "feat: wire per-player conversation sessions into handle_mention"
```

---

### Task 4: Clear session on player logout

**Files:**
- Modify: `swee/log_tailer.py`

**Interfaces:**
- Consumes: `assistant.resolve_player_id(name, online_players)` (Task 1), `assistant.clear_session(player_id)` (Task 1), `online_players` from `swee/player_history.py`.

- [ ] **Step 1: Add the import**

`swee/log_tailer.py` currently imports `from swee.player_history import record_join, record_leave`. Change it to also import `online_players`:

```python
from swee.player_history import online_players, record_join, record_leave
```

- [ ] **Step 2: Resolve and clear the session in the LEAVE_RE branch**

The current `LEAVE_RE` branch (in the `async for line in proc.stdout` loop, alongside `CONNECT_RE`/`JOIN_RE`/`CHAT_RE`) reads:

```python
                    elif m := LEAVE_RE.search(rest_msg):
                        name = m.group(1)
                        if pending := pending_connects.pop(name, None):
                            pending.cancel()
                        await broadcast_embed(f"{name} left the server", None, COLOR_LEAVE, dt)
                        await record_leave(name, dt)
                        await update_stats_message()
```

Add the session clear, resolving the player id *before* `record_leave` is called (since `record_leave` pops the player out of `online_players` as part of its own bookkeeping):

```python
                    elif m := LEAVE_RE.search(rest_msg):
                        name = m.group(1)
                        if pending := pending_connects.pop(name, None):
                            pending.cancel()
                        assistant.clear_session(assistant.resolve_player_id(name, online_players))
                        await broadcast_embed(f"{name} left the server", None, COLOR_LEAVE, dt)
                        await record_leave(name, dt)
                        await update_stats_message()
```

(`swee.assistant` is already imported in this file as `assistant`, from the original `@swee` feature's log-tailer wiring — no new import needed for that part.)

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `python -m unittest discover tests -v`
Expected: PASS, same test count as after Task 3 (no new tests — `log_tailer.py` has no test harness per `CLAUDE.md`, verified manually below).

- [ ] **Step 4: Manually verify session clearing logic**

No live server needed for this specific check — verify the resolve-then-clear ordering is correct by reasoning through a quick standalone script:

```bash
python -c "
import swee.assistant as assistant
from swee.player_history import online_players

online_players['TestPlayer'] = 'steam_999'
assistant._sessions['steam_999'] = [{'role': 'user', 'content': 'hi'}]

player_id = assistant.resolve_player_id('TestPlayer', online_players)
assistant.clear_session(player_id)

print('steam_999' in assistant._sessions)
"
```

Expected: prints `False` — confirms `resolve_player_id` correctly finds `steam_999` via `online_players` and `clear_session` removes it. (This mirrors exactly what the `LEAVE_RE` branch now does before `record_leave` would otherwise pop `online_players['TestPlayer']`.) Full end-to-end verification (a real player leaving a real server) is deferred to deploy, matching this repo's established convention for the log-tailer layer.

- [ ] **Step 5: Commit**

```bash
git add swee/log_tailer.py
git commit -m "feat: clear player's assistant session on server leave"
```

---

### Task 5: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing (docs only).

- [ ] **Step 1: Update the assistant feature description**

In `README.md`, the existing `### In-game @swee assistant (optional)` section currently ends with:

```markdown
Known limitation: map/resource-location questions (e.g. "where can I find Pure Quartz") aren't
grounded in live data — there's no pal to look up, so these fall back to Claude's general knowledge
and can be vague or wrong. Only pal-specific questions (breeding, drops, work suitability, stats,
passive skills) are backed by a live lookup.
```

Insert a new paragraph before that "Known limitation" paragraph, describing session memory:

```markdown
Each player's questions and answers are remembered as a conversation within their current play
session (up to the last 8 exchanges), so follow-up questions like "what about its passive skills?"
can reference what was already asked — this memory is cleared when the player leaves the server, and
is never shared between players even if they share a display name.
```

- [ ] **Step 2: Run the full test suite to confirm no regressions**

Run: `python -m unittest discover tests -v`
Expected: PASS (docs-only change, no test impact).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document @swee per-player conversation sessions"
```

## Self-Review

**Spec coverage:**
- Identity resolution via `userId` (not display name), with fallback → Task 1 (`resolve_player_id`). ✓
- Cooldown re-keyed to `player_id` → Task 3 (`handle_mention` uses `player_id` for `is_on_cooldown`/`record_answered`). ✓
- Session storage as simplified text pairs, not raw tool-use blocks → Task 2 (`append_exchange` stores only `question`/`answer` text; `ask_claude`'s internal tool loop messages are never passed to `append_exchange`). ✓
- 8-exchange cap → Task 2 (`SESSION_HISTORY_LIMIT = 8`, `append_exchange`'s trim logic). ✓
- `ask_claude` history parameter → Task 2. ✓
- Only successful answers saved to session → Task 3 (`append_exchange` called only inside the `try` block, before the `except`). ✓
- Session cleared on logout, resolved before `record_leave` pops `online_players` → Task 4. ✓
- No new module; import `online_players` directly from `player_history.py`, matching `commands.py` precedent → Task 1/3/4 (`from swee.player_history import online_players` in both `assistant.py` and `log_tailer.py`). ✓
- No persistence across restarts, no inactivity timeout → nothing to build (deliberately out of scope, no task needed). ✓
- Documentation → Task 5. ✓

**Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `resolve_player_id`, `pop_session`, `clear_session`, `append_exchange`, `ask_claude`, `handle_mention` are used with the same names and signatures everywhere they're referenced across tasks. `_sessions` and `SESSION_HISTORY_LIMIT` are defined once (Task 1/2) and consumed identically in Task 3.
