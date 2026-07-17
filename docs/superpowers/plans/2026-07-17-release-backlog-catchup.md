# Release Backlog Catch-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `release_ticker` finds it's behind by more than one GitHub release, announce every
missed release in `#bot-updates`, oldest first, instead of silently skipping straight to the
newest one.

**Architecture:** Swap the single-release `/releases/latest` GitHub API call for the list endpoint
(`/releases`, newest-first, `per_page=100`). A new pure function, `select_missed_releases`, walks
that list and returns everything newer than the cached tag, oldest first. `release_ticker` loops
over that result, announcing and saving progress one release at a time so a mid-loop failure never
causes a re-announcement on retry.

**Tech Stack:** Python 3.14, `httpx` (async GitHub API calls), `discord.py` (`tasks.loop`),
`unittest` (existing test runner, `python -m unittest discover tests -v`).

## Global Constraints

- No cap on backlog size — however many releases are missed, all get announced (per
  `docs/superpowers/specs/2026-07-17-release-backlog-catchup-design.md`, Scope).
- No pagination beyond one page of 100 releases — if the cached tag isn't found within the first
  100, all 100 are announced and the cached tag becomes the oldest one seen.
- `last_release.json` is saved after **every individual successful announcement**, not once per
  tick.
- A failed `broadcast_embed` call stops the loop for that tick (no skipping ahead) and is retried,
  in order, on the next tick.
- First-run seeding behavior (seed silently, don't announce, when `last_release_tag` is `None`) is
  unchanged.
- No changes to `humanize_release_notes`, `parse_release_header`, or the embed format/content.
- Follow existing code style in `swee/releases.py`: no docstrings (the codebase has effectively
  none), short comments only where behavior is genuinely non-obvious.

---

### Task 1: `select_missed_releases` pure function

**Files:**
- Modify: `swee/releases.py` (add function near `parse_release_header`, after its definition
  around line 42)
- Test: `tests/test_releases.py` (add new `TestCase` class after `HumanizeReleaseNotesTests`,
  before `ParseReleaseHeaderTests`)

**Interfaces:**
- Consumes: nothing from other tasks — pure function, no dependencies beyond stdlib.
- Produces: `select_missed_releases(releases: list[dict], last_tag: str) -> list[dict]`. `releases`
  is a list of GitHub release objects (dicts with at least a `"tag_name"` key) in newest-first
  order, matching what `GET /repos/{repo}/releases` returns. Returns the subset that came after
  `last_tag`, reordered oldest-first. If `last_tag` doesn't appear in `releases` at all, every
  entry in `releases` is treated as missed. Task 3 (`release_ticker`) calls this with a non-`None`
  `last_tag` (it handles the `None`/first-run case itself before calling).

- [ ] **Step 1: Write the failing tests**

Add this new test class to `tests/test_releases.py`, right after the `HumanizeReleaseNotesTests`
class (before `class ParseReleaseHeaderTests`):

```python
class SelectMissedReleasesTests(unittest.TestCase):
    def test_returns_releases_after_last_tag_oldest_first(self):
        releases = [
            {"tag_name": "v2.5.2", "body": "c"},
            {"tag_name": "v2.5.1", "body": "b"},
            {"tag_name": "v2.5.0", "body": "a"},
        ]
        missed = select_missed_releases(releases, "v2.5.0")
        self.assertEqual([r["tag_name"] for r in missed], ["v2.5.1", "v2.5.2"])

    def test_returns_empty_list_when_last_tag_is_newest(self):
        releases = [{"tag_name": "v2.5.0", "body": "a"}]
        self.assertEqual(select_missed_releases(releases, "v2.5.0"), [])

    def test_treats_all_releases_as_missed_when_last_tag_not_found(self):
        releases = [
            {"tag_name": "v2.5.2", "body": "c"},
            {"tag_name": "v2.5.1", "body": "b"},
        ]
        missed = select_missed_releases(releases, "v2.4.0")
        self.assertEqual([r["tag_name"] for r in missed], ["v2.5.1", "v2.5.2"])

    def test_returns_empty_list_for_empty_releases(self):
        self.assertEqual(select_missed_releases([], "v2.5.0"), [])
```

Also update the import line near the top of the file from:

```python
from swee.releases import humanize_release_notes, parse_release_header  # noqa: E402
```

to:

```python
from swee.releases import (  # noqa: E402
    humanize_release_notes,
    parse_release_header,
    select_missed_releases,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_releases -v`
Expected: `ImportError: cannot import name 'select_missed_releases'` (function doesn't exist yet).

- [ ] **Step 3: Implement the function**

In `swee/releases.py`, add this function directly after `parse_release_header` (after the line
`return None, None` that closes it, around line 42), before the `ENV_VAR_MENTION_RE` line:

```python
def select_missed_releases(releases, last_tag):
    # releases is newest-first (GitHub API order). Stop as soon as last_tag is found; if it's
    # never found (backlog bigger than one page), every entry here counts as missed.
    missed = []
    for release in releases:
        if release.get("tag_name") == last_tag:
            break
        missed.append(release)
    missed.reverse()
    return missed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_releases -v`
Expected: all tests pass, including the 4 new `SelectMissedReleasesTests` cases.

- [ ] **Step 5: Commit**

```bash
git add swee/releases.py tests/test_releases.py
git commit -m "feat: add select_missed_releases for backlog catch-up"
```

---

### Task 2: Replace `fetch_latest_release` with `fetch_releases`

**Files:**
- Modify: `swee/releases.py:72-80` (the `fetch_latest_release` function)

**Interfaces:**
- Consumes: `GITHUB_REPO`, `GITHUB_TOKEN` from `swee.config` (already imported at the top of
  `swee/releases.py` — no import changes needed).
- Produces: `async def fetch_releases() -> list[dict]`, replacing `fetch_latest_release`. Returns
  the JSON array from `GET /repos/{repo}/releases?per_page=100` (newest-first). Task 3
  (`release_ticker`) calls `await fetch_releases()` in place of `await fetch_latest_release()`.

This task has no unit test: it's a thin network call with the same shape and auth handling as the
`fetch_latest_release` it replaces, which itself was never unit tested (per
`docs/superpowers/specs/2026-07-17-release-backlog-catchup-design.md`, Testing approach — network/
Discord-touching code in this file has no test harness). Verification is a full test-suite run
(to confirm nothing else broke) plus a manual read-through against the GitHub API docs shape.

- [ ] **Step 1: Replace the function**

In `swee/releases.py`, replace the existing `fetch_latest_release` function (lines 72-80):

```python
async def fetch_latest_release():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()
```

with:

```python
async def fetch_releases():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=headers, params={"per_page": 100})
        r.raise_for_status()
        return r.json()
```

- [ ] **Step 2: Run the full test suite to confirm nothing broke**

Run: `python -m unittest discover tests -v`
Expected: all tests pass (this function isn't directly tested, but the run confirms the module
still imports and nothing else regressed).

- [ ] **Step 3: Commit**

```bash
git add swee/releases.py
git commit -m "feat: fetch full release list instead of just the latest release"
```

---

### Task 3: Rewrite `release_ticker` to announce the full backlog

**Files:**
- Modify: `swee/releases.py:118-159` (the `release_ticker` function)

**Interfaces:**
- Consumes: `fetch_releases()` (Task 2), `select_missed_releases(releases, last_tag)` (Task 1),
  and the existing `parse_release_header`, `humanize_release_notes`, `broadcast_embed`,
  `save_last_release`, `last_release_tag` module global — all already defined/imported in
  `swee/releases.py`.
- Produces: the updated `release_ticker` coroutine (same name, same `@tasks.loop(minutes=5)`
  decorator, same external behavior contract as before — started/cancelled from `main.py`, no
  changes needed there).

This task also has no new unit test, for the same reason as Task 2 — `release_ticker` is a
`tasks.loop` coroutine that calls out to the network and Discord, matching the untested pattern of
`stats_ticker` (per the design spec's Testing approach section). Verification is the full test
suite (confirms the pure functions it calls are still wired correctly) plus a manual trace of the
new logic against the design spec's Data Flow section.

- [ ] **Step 1: Replace the function**

In `swee/releases.py`, replace the existing `release_ticker` function (lines 118-159):

```python
@tasks.loop(minutes=5)
async def release_ticker():
    global last_release_tag
    try:
        release = await fetch_latest_release()
    except Exception:
        log.exception("release check failed")
        return

    tag = release.get("tag_name")
    if not tag:
        return

    if last_release_tag is None:
        # First run with no cached state — seed it without announcing, so
        # shipping this feature doesn't dump a changelog for a release that
        # already happened before the bot could track it.
        save_last_release(tag)
        return

    if tag == last_release_tag:
        return

    body = release.get("body") or ""
    _, release_date = parse_release_header(body)
    notes = humanize_release_notes(body)
    if notes is None:
        notes = body or "No release notes."
        max_len = 4000
        if len(notes) > max_len:
            notes = notes[:max_len] + "…"
    sent = await broadcast_embed(
        "New Release",
        notes,
        COLOR_READY,
        dt=release_date,
        channel_id=BOT_UPDATES_CHANNEL_ID,
    )
    if sent:
        save_last_release(tag)
    else:
        log.warning("release announcement failed for %s, will retry next tick", tag)
```

with:

```python
@tasks.loop(minutes=5)
async def release_ticker():
    global last_release_tag
    try:
        releases = await fetch_releases()
    except Exception:
        log.exception("release check failed")
        return

    if not releases:
        return

    newest_tag = releases[0].get("tag_name")
    if not newest_tag:
        return

    if last_release_tag is None:
        # First run with no cached state — seed it without announcing, so
        # shipping this feature doesn't dump a changelog for releases that
        # already happened before the bot could track them.
        save_last_release(newest_tag)
        return

    if newest_tag == last_release_tag:
        return

    for release in select_missed_releases(releases, last_release_tag):
        tag = release.get("tag_name")
        if not tag:
            continue
        body = release.get("body") or ""
        _, release_date = parse_release_header(body)
        notes = humanize_release_notes(body)
        if notes is None:
            notes = body or "No release notes."
            max_len = 4000
            if len(notes) > max_len:
                notes = notes[:max_len] + "…"
        sent = await broadcast_embed(
            "New Release",
            notes,
            COLOR_READY,
            dt=release_date,
            channel_id=BOT_UPDATES_CHANNEL_ID,
        )
        if sent:
            save_last_release(tag)
        else:
            log.warning("release announcement failed for %s, will retry next tick", tag)
            break
```

- [ ] **Step 2: Run the full test suite**

Run: `python -m unittest discover tests -v`
Expected: all tests pass.

- [ ] **Step 3: Manually trace the logic against a constructed backlog scenario**

With `last_release_tag = "v2.5.0"` and a hypothetical `fetch_releases()` response of
`[{"tag_name": "v2.5.2", ...}, {"tag_name": "v2.5.1", ...}, {"tag_name": "v2.5.0", ...}]`:
confirm by reading the code that `select_missed_releases` returns `v2.5.1` then `v2.5.2` (oldest
first), that both get announced in that order, and that `last_release_tag` is `"v2.5.2"` after the
tick. This is a read-through, not an automated step — there's no test harness for the network/
Discord-touching coroutine itself (see Task 2/3 rationale above).

- [ ] **Step 4: Commit**

```bash
git add swee/releases.py
git commit -m "feat: announce every missed release in order, not just the newest"
```

---

### Task 4: Update README to describe backlog catch-up

**Files:**
- Modify: `README.md` (the "Release announcements" section, around lines 47-56)

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: nothing consumed by other tasks.

- [ ] **Step 1: Update the section text**

In `README.md`, replace:

```
If `GITHUB_REPO` is set, every 5 minutes the bot polls the GitHub Releases API for the latest
release; when a new one appears, it humanizes the auto-generated release notes (Conventional
Commit prefixes and PR references stripped, grouped into "New"/"Fixes") and posts an embed to
`BOT_UPDATES_CHANNEL_ID`. The last announced tag is cached in `last_release.json`; deleting that
file makes the bot re-seed from the current latest release on next startup without re-announcing
it. If `GITHUB_REPO` is private, set `GITHUB_TOKEN` to a token with read access — unauthenticated
requests to the GitHub API 404 on private repos instead of returning release data. Leave
`GITHUB_REPO` unset/blank to disable release polling entirely.
```

with:

```
If `GITHUB_REPO` is set, every 5 minutes the bot polls the GitHub Releases API; when new releases
appear, it humanizes each one's auto-generated release notes (Conventional Commit prefixes and PR
references stripped, grouped into "New"/"Fixes") and posts an embed to `BOT_UPDATES_CHANNEL_ID`.
If more than one release shipped since the last check (e.g. the bot was offline), it announces all
of them in order, oldest first, rather than skipping straight to the newest. The last announced
tag is cached in `last_release.json`; deleting that file makes the bot re-seed from the current
latest release on next startup without re-announcing it. If `GITHUB_REPO` is private, set
`GITHUB_TOKEN` to a token with read access — unauthenticated requests to the GitHub API 404 on
private repos instead of returning release data. Leave `GITHUB_REPO` unset/blank to disable
release polling entirely.
```

- [ ] **Step 2: Verify no other README section references the old single-release behavior**

Run: `grep -n "latest release\|releases/latest" README.md`
Expected: no matches (the only prior reference was the paragraph just replaced).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: describe release backlog catch-up behavior"
```
