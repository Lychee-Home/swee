# Release Announcements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a new GitHub Release is published for this repo, the bot posts a player-friendly changelog embed to a new `#bot-updates` channel.

**Architecture:** A new `tasks.loop(minutes=5)` in `main.py` (`release_ticker`) polls the GitHub Releases API, compares the latest tag against a cached "last announced tag" persisted in `last_release.json`, and — on a new tag — humanizes the auto-generated release notes (strip Conventional Commit prefixes / PR back-references, group into "New"/"Fixes") before posting via the existing `broadcast_embed` helper.

**Tech Stack:** Python 3.14, `httpx` (already a dependency), `discord.py` `tasks.loop` (same pattern as the existing `stats_ticker`).

## Global Constraints

- Single-file bot — all changes go in `main.py`; no new package/module structure (per `CLAUDE.md`).
- No test runner exists in this repo — verification is manual/hand-run, per the design spec's Testing Approach section. Do not add a test framework or dependency.
- New env vars go in `.env.example` with a comment, following the existing style in that file.
- Only `feat`/`fix`/`perf` Conventional Commit types are player-relevant (matches the versioning scheme in `docs/superpowers/specs/2026-07-10-release-versioning-design.md`).
- Full design reference: `docs/superpowers/specs/2026-07-10-release-announcements-design.md`.

---

### Task 1: Config — new env vars and gitignore entry

**Files:**
- Modify: `main.py:22-41` (env var block)
- Modify: `.env.example`
- Modify: `.gitignore`

**Interfaces:**
- Produces: module-level constants `BOT_UPDATES_CHANNEL_ID: int` and `GITHUB_REPO: str`, readable by later tasks exactly like the existing `ACTIVITY_CHANNEL_ID` / `ALERTS_CHANNEL_ID` constants.

- [ ] **Step 1: Add the two new env vars to `main.py`**

In `main.py`, immediately after the existing block:

```python
ACTIVITY_CHANNEL_ID = int(os.environ["ACTIVITY_CHANNEL_ID"])
ALERTS_CHANNEL_ID   = int(os.environ["ALERTS_CHANNEL_ID"])
```

add:

```python
BOT_UPDATES_CHANNEL_ID = int(os.environ["BOT_UPDATES_CHANNEL_ID"])
GITHUB_REPO            = os.environ["GITHUB_REPO"]
```

- [ ] **Step 2: Add the same vars to `.env.example`**

Add a new section after the existing `# --- Discord channels ---` block's channel IDs (i.e. after the `COMMANDS_CHANNEL_ID` line, before `# --- Palworld REST API ---`):

```
BOT_UPDATES_CHANNEL_ID=123456789012345678
```

And a new section near the end of the file (after the `# --- Player history (optional) ---` block):

```

# --- Release announcements ---
# Repo the bot polls for new GitHub Releases to announce in BOT_UPDATES_CHANNEL_ID.
GITHUB_REPO=byroncustodio/swee
```

- [ ] **Step 3: Add `last_release.json` to `.gitignore`**

Append a new line to `.gitignore`, next to the existing `player_history.json` entry:

```
last_release.json
```

- [ ] **Step 4: Commit**

```bash
git add main.py .env.example .gitignore
git commit -m "feat: add config for release announcements"
```

---

### Task 2: Humanizer — `humanize_release_notes`

**Files:**
- Modify: `main.py` (add near the other formatting helpers, e.g. after `format_offline_field`, around `main.py:242`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `humanize_release_notes(body: str) -> str | None` — returns humanized text, or `None` if no `feat`/`fix`/`perf` line could be parsed out of `body`. Later tasks (Task 4) call this and fall back to the raw body when it returns `None`.

- [ ] **Step 1: Add the regex, label map, and function**

Add this block to `main.py` (near the other module-level regexes at the top, e.g. next to `UPGRADE_LOG_RE`, and the function itself down with the other formatting helpers — regex constants belong with the other `_RE` constants for consistency):

Regex constant (add next to `UPGRADE_LOG_RE` around `main.py:50-52`):

```python
RELEASE_NOTE_RE = re.compile(
    r'^\*\s*(?P<type>\w+)(\([^)]*\))?!?:\s*(?P<desc>.+?)\s+by\s+@\S+\s+in\s+\S+$'
)
RELEASE_NOTE_LABELS = {"feat": "🆕 New", "fix": "🛠️ Fixes", "perf": "🛠️ Fixes"}
```

Function (add after `format_offline_field`, around `main.py:242`):

```python
def humanize_release_notes(body):
    grouped = {}
    for line in body.splitlines():
        m = RELEASE_NOTE_RE.match(line.strip())
        if not m:
            continue
        label = RELEASE_NOTE_LABELS.get(m.group("type"))
        if not label:
            continue
        desc = m.group("desc").strip()
        if desc:
            desc = desc[0].upper() + desc[1:]
        grouped.setdefault(label, []).append(desc)

    if not grouped:
        return None

    sections = []
    for label in ("🆕 New", "🛠️ Fixes"):
        if label in grouped:
            lines = "\n".join(f"• {d}" for d in grouped[label])
            sections.append(f"{label}\n{lines}")
    return "\n\n".join(sections)
```

- [ ] **Step 2: Hand-verify against a real release body**

With your `.env` populated (per README Setup — any valid-looking values work, nothing here calls Discord or the REST API), run:

```bash
python -c "
from main import humanize_release_notes
body = '''## What's Changed
* fix: require BREAKING CHANGE: to start a line, not just appear anywhere by @byroncustodio in #4
* feat: add automated semantic-version release tagging by @byroncustodio in #3
* chore: bump dependency pins by @byroncustodio in #5

**Full Changelog**: https://github.com/byroncustodio/swee/compare/v1.1.0...v1.2.0'''
print(humanize_release_notes(body))
"
```

Expected output:

```
🆕 New
• Add automated semantic-version release tagging

🛠️ Fixes
• Require BREAKING CHANGE: to start a line, not just appear anywhere
```

(Note the `chore:` line and the `**Full Changelog**` line are both dropped.)

- [ ] **Step 3: Hand-verify the fallback case**

Run:

```bash
python -c "
from main import humanize_release_notes
print(humanize_release_notes('Manually written release notes with no bullet list.'))
"
```

Expected output: `None`

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add release notes humanizer"
```

---

### Task 3: State — `last_release.json` load/save

**Files:**
- Modify: `main.py` (near `load_player_history`/`save_player_history`, `main.py:141-163`)
- Modify: `main.py:689-695` (`main()`, to load state at startup)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: module-level `last_release_tag: str | None`, plus `load_last_release() -> None` and `save_last_release(tag: str) -> None`. Task 4's `release_ticker` reads/writes `last_release_tag` and calls `save_last_release`.

- [ ] **Step 1: Add state constant and variable**

Next to the existing player-history state block (`main.py:140-144`):

```python
LAST_RELEASE_PATH = "last_release.json"
last_release_tag = None  # cached in-memory; mirrors last_release.json on disk
```

- [ ] **Step 2: Add load/save functions**

Add after `save_player_history` (around `main.py:163`):

```python
def load_last_release():
    global last_release_tag
    try:
        with open(LAST_RELEASE_PATH) as f:
            last_release_tag = json.load(f).get("tag")
    except FileNotFoundError:
        last_release_tag = None
    except json.JSONDecodeError:
        log.warning("last_release.json is corrupt, starting with no cached tag")
        last_release_tag = None


def save_last_release(tag):
    global last_release_tag
    last_release_tag = tag
    with open(LAST_RELEASE_PATH, "w") as f:
        json.dump({"tag": tag}, f, indent=2)
```

- [ ] **Step 3: Call `load_last_release()` at startup**

In `main()`, next to the existing `load_player_history()` call:

```python
async def main():
    discord.utils.setup_logging()
    if not check_palworld_service():
        raise SystemExit(1)
    load_player_history()
    load_last_release()
    async with bot:
```

- [ ] **Step 4: Hand-verify round-trip**

```bash
python -c "
from main import load_last_release, save_last_release, last_release_tag
import main
load_last_release()
print('initial:', main.last_release_tag)
save_last_release('v9.9.9')
print('after save:', main.last_release_tag)
load_last_release()
print('reloaded from disk:', main.last_release_tag)
"
rm -f last_release.json
```

Expected output:
```
initial: None
after save: v9.9.9
reloaded from disk: v9.9.9
```

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: add last-announced-release state tracking"
```

---

### Task 4: Polling loop — `release_ticker`

**Files:**
- Modify: `main.py` (near `stats_ticker`, `main.py:377-397`)
- Modify: `main.py:678-686` (`on_ready`, to start the ticker)
- Modify: `main.py:689-701` (`main()`, to cancel the ticker on shutdown)

**Interfaces:**
- Consumes: `humanize_release_notes(body: str) -> str | None` (Task 2), `last_release_tag` / `load_last_release` / `save_last_release` (Task 3), `broadcast_embed(title, description, color, dt=None, channel_id=ACTIVITY_CHANNEL_ID, fields=None)` (existing, `main.py:117`), `BOT_UPDATES_CHANNEL_ID` / `GITHUB_REPO` (Task 1), `COLOR_READY` (existing constant).
- Produces: `fetch_latest_release() -> dict`, `tasks.loop` object `release_ticker`.

- [ ] **Step 1: Add `fetch_latest_release`**

Add near the other network helpers (after the `PalRestClient` class / `rest = PalRestClient()`, around `main.py:83`):

```python
async def fetch_latest_release():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        return r.json()
```

- [ ] **Step 2: Add `release_ticker`**

Add after `stats_ticker` (around `main.py:397`):

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
    notes = humanize_release_notes(body) or body or "No release notes."
    await broadcast_embed(
        f"\U0001f389 {tag} released",
        notes,
        COLOR_READY,
        channel_id=BOT_UPDATES_CHANNEL_ID,
    )
    save_last_release(tag)
```

- [ ] **Step 3: Start the ticker in `on_ready`**

In `on_ready` (`main.py:678-686`), next to `stats_ticker.start()`:

```python
    _log_tailer_task = asyncio.create_task(log_tailer())
    stats_ticker.start()
    release_ticker.start()
    log.info("Logged in as %s", bot.user)
```

- [ ] **Step 4: Cancel the ticker on shutdown in `main()`**

In `main()` (`main.py:689-701`), next to `stats_ticker.cancel()`:

```python
        stats_ticker.cancel()
        release_ticker.cancel()
        if _log_tailer_task:
```

- [ ] **Step 5: Hand-verify `fetch_latest_release` against the real repo**

```bash
python -c "
import asyncio
from main import fetch_latest_release
release = asyncio.run(fetch_latest_release())
print(release['tag_name'])
print(release['body'][:200])
"
```

Expected: prints the current latest tag (e.g. `v1.2.0`) and the start of its generated notes — confirms the request, auth-less headers, and JSON shape all work against the real GitHub API.

- [ ] **Step 6: Manual end-to-end smoke test**

This step can't be scripted (it needs a running bot + a real Discord channel), so do it once after deploying:
1. Set `BOT_UPDATES_CHANNEL_ID` to a real `#bot-updates` channel and `GITHUB_REPO=byroncustodio/swee` in `.env`.
2. Delete any stale `last_release.json` so the bot seeds fresh.
3. Start the bot (`python main.py` on the Linux host, or via `systemctl restart swee` once deployed) and confirm via logs that `release_ticker` ran once with no message posted (first-run seeding).
4. Confirm `last_release.json` now contains the current latest tag.
5. Merge a `fix:`/`feat:` PR to trigger a real new release, wait up to 5 minutes, and confirm the embed posts to `#bot-updates` with humanized text.

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "feat: poll GitHub releases and announce new ones"
```

---

### Task 5: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing (docs only).
- Produces: nothing consumed by other tasks.

- [ ] **Step 1: Document the feature in the "How it works" section**

Add a new bullet after the existing "Relay channel" bullet (`README.md:30-31`):

```markdown
- **Release announcements** — every 5 minutes the bot polls the GitHub Releases API
  (`GITHUB_REPO`) for the latest release; when a new one appears, it humanizes the
  auto-generated release notes (Conventional Commit prefixes and PR references stripped,
  grouped into "New"/"Fixes") and posts an embed to `BOT_UPDATES_CHANNEL_ID`. The last
  announced tag is cached in `last_release.json`; deleting that file makes the bot
  re-seed from the current latest release on next startup without re-announcing it.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document release announcements feature"
```

---

## Self-Review Notes

- **Spec coverage:** polling/state/first-run behavior → Tasks 3–4; humanization/grouping/fallback → Task 2; config → Task 1; error handling (logged + skipped, never crashes ticker) → Task 4 Step 2 (`try/except` around `fetch_latest_release`, mirrors `stats_ticker`); docs → Task 5. No gaps found.
- **Placeholder scan:** none — every step has literal code or an exact command with expected output.
- **Type consistency:** `humanize_release_notes(body: str) -> str | None` used identically in Task 2 (definition) and Task 4 Step 2 (call site). `last_release_tag`, `load_last_release`, `save_last_release` used identically across Tasks 3 and 4.
