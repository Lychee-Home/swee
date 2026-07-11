# Palworld settings change alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the Palworld server comes back online after any restart, detect whether
`PalWorldSettings.ini` changed since the last check and post a Discord alert listing what changed.

**Architecture:** All new code lives in `main.py` (single-file bot, per `CLAUDE.md` — no package
structure without asking first). A small hand-rolled parser turns the ini's single
`OptionSettings=(...)` line into a flat `{key: value}` dict. That dict is diffed against a JSON
snapshot cached on disk (`last_palworld_settings.json`, mirroring the existing
`last_release.json` pattern), and diffs are posted to `ALERTS_CHANNEL_ID` via the existing
`broadcast_embed` helper. The check is triggered from the existing `VERSION_RE` branch in
`log_tailer()`, which already fires every time the server comes back online.

**Tech Stack:** Python 3.14, stdlib `re`/`json`/`asyncio` only — no new dependencies.

## Global Constraints

- No package/module split — everything goes in `main.py` (see `CLAUDE.md`).
- No new dependencies (spec calls for a hand-rolled parser, not a library).
- `AdminPassword`/`ServerPassword` values must never appear in plaintext in a Discord embed —
  render as `(changed)` when they're among the changed keys.
- First run with no cached snapshot must seed silently — no alert.
- Discord embeds cap at 25 fields — more than 25 changed keys must be truncated with a summary
  field, not silently dropped or a `discord.HTTPException`.
- Any parse/diff failure must be caught and logged, never crash `log_tailer`'s loop or block the
  existing "Server is online" alert.
- This repo has no automated test runner (`CLAUDE.md`): verify each unit manually via one-off
  `python -c` invocations, not a pytest suite.

---

### Task 1: Config plumbing — `PALWORLD_SETTINGS_INI_PATH`

**Files:**
- Modify: `.env.example`
- Modify: `main.py:33-36` (env var block, right after `ALERTS_CHANNEL_ID`/`BOT_UPDATES_CHANNEL_ID`/`GITHUB_REPO`)

**Interfaces:**
- Produces: module-level constant `PALWORLD_SETTINGS_INI_PATH: str` in `main.py`, used by Task 2's
  parser call in Task 4's wiring.

- [ ] **Step 1: Add the env var to `.env.example`**

Add this block after the `GITHUB_REPO` section (end of file):

```
# --- Palworld settings change alert ---
# Absolute path to PalWorldSettings.ini on this host. Checked for changes every time the
# server comes back online after a restart; differences are posted to ALERTS_CHANNEL_ID.
PALWORLD_SETTINGS_INI_PATH=/home/steam/Steam/steamapps/common/PalServer/Pal/Saved/Config/LinuxServer/PalWorldSettings.ini
```

- [ ] **Step 2: Add the constant to `main.py`**

In `main.py`, right after the existing block:

```python
ACTIVITY_CHANNEL_ID = int(os.environ["ACTIVITY_CHANNEL_ID"])
ALERTS_CHANNEL_ID   = int(os.environ["ALERTS_CHANNEL_ID"])
BOT_UPDATES_CHANNEL_ID = int(os.environ["BOT_UPDATES_CHANNEL_ID"])
GITHUB_REPO            = os.environ["GITHUB_REPO"]
```

add:

```python
PALWORLD_SETTINGS_INI_PATH = os.environ["PALWORLD_SETTINGS_INI_PATH"]
```

- [ ] **Step 3: Verify the new line is syntactically valid**

```bash
python -c "import ast; ast.parse(open('main.py').read())"
```

Expected: no output (success). This only checks syntax; full import (which requires every env
var, including `PALWORLD_SETTINGS_INI_PATH`, to be set) is verified in Task 2 Step 3 once there's
a runnable fixture.

- [ ] **Step 4: Commit**

```bash
git add .env.example main.py
git commit -m "feat: add PALWORLD_SETTINGS_INI_PATH config"
```

---

### Task 2: Ini parser

**Files:**
- Modify: `main.py` — add near the other regex constants (after `RELEASE_NOTE_SECTION_ORDER`,
  around line 61) and a new section before `# ---------- REST client ----------`.

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `OPTION_SETTINGS_RE` (module-level compiled regex), `parse_palworld_settings(path: str) -> dict[str, str]` (raises `FileNotFoundError` if the file doesn't exist, `ValueError` if no `OptionSettings` line is found). Used by Task 5's `check_palworld_settings_change`.

- [ ] **Step 1: Add the regex constant**

After `RELEASE_NOTE_SECTION_ORDER = tuple(dict.fromkeys(RELEASE_NOTE_LABELS.values()))` in
`main.py`, add:

```python
OPTION_SETTINGS_RE = re.compile(r'OptionSettings=\((.*)\)\s*$')
```

- [ ] **Step 2: Add the parser section and functions**

Add a new section right before `# ---------- REST client ----------`:

```python
# ---------- PalWorldSettings.ini parsing ----------
def _parse_option_settings(text):
    """Split the inner content of OptionSettings=(...) into a {key: value} dict.

    Values are either bare tokens (numbers, enum names, True/False) or double-quoted
    strings that may contain commas (e.g. ServerDescription="Hello, world") — a plain
    comma-split would break on those, so this scans char-by-char instead.
    """
    pairs = {}
    i, n = 0, len(text)
    while i < n:
        eq = text.index('=', i)
        key = text[i:eq]
        i = eq + 1
        if i < n and text[i] == '"':
            end = text.index('"', i + 1)
            value = text[i:end + 1]
            i = end + 1
            if i < n and text[i] == ',':
                i += 1
        else:
            comma = text.find(',', i)
            if comma == -1:
                value = text[i:]
                i = n
            else:
                value = text[i:comma]
                i = comma + 1
        pairs[key] = value
    return pairs


def parse_palworld_settings(path):
    with open(path) as f:
        content = f.read()
    m = OPTION_SETTINGS_RE.search(content)
    if not m:
        raise ValueError(f"no OptionSettings line found in {path}")
    return _parse_option_settings(m.group(1))
```

- [ ] **Step 3: Verify manually with a fixture file**

Create a fixture, then verify by running Python with required env vars stubbed so `main.py`
imports cleanly (no bot connection is made — importing the module just parses top-level code):

```bash
mkdir -p /tmp/swee-test
cat > /tmp/swee-test/sample.ini << 'EOF'
[/Script/Pal.PalGameWorldSettings]
OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,ServerName="My Server, the best",ServerPassword="hunter2",ExpRate=2.000000)
EOF
cd /path/to/swee
DISCORD_BOT_TOKEN=x GUILD_ID=1 ADMIN_ROLE_ID=1 STATS_CHANNEL_ID=1 ACTIVITY_CHANNEL_ID=1 \
ALERTS_CHANNEL_ID=1 ADMIN_CHANNEL_ID=1 COMMANDS_CHANNEL_ID=1 BOT_UPDATES_CHANNEL_ID=1 \
REST_HOST=x REST_PORT=1 REST_USER=x REST_PASSWORD=x GITHUB_REPO=x/y \
PALWORLD_SETTINGS_INI_PATH=/tmp/swee-test/sample.ini \
python -c "
from main import parse_palworld_settings
result = parse_palworld_settings('/tmp/swee-test/sample.ini')
assert result['Difficulty'] == 'None', result
assert result['DayTimeSpeedRate'] == '1.000000', result
assert result['ServerName'] == '\"My Server, the best\"', result
assert result['ServerPassword'] == '\"hunter2\"', result
assert result['ExpRate'] == '2.000000', result
print('OK', result)
"
```

Expected: `OK {'Difficulty': 'None', 'DayTimeSpeedRate': '1.000000', 'ServerName': '"My Server, the best"', 'ServerPassword': '"hunter2"', 'ExpRate': '2.000000'}`

(Note: this is the first task where `main.py` is actually imported, so it also confirms Task 1's
new line doesn't break startup.)

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add PalWorldSettings.ini parser"
```

---

### Task 3: Snapshot cache, diff, and embed formatting

**Files:**
- Modify: `main.py` — add near the existing `LAST_RELEASE_PATH` state block (around line 166-204).

**Interfaces:**
- Consumes: nothing new (works on plain dicts).
- Produces: `PALWORLD_SETTINGS_CACHE_PATH` (str constant), `last_palworld_settings` (module-level
  dict-or-`None`), `load_last_palworld_settings()`, `save_last_palworld_settings(settings: dict)`,
  `diff_palworld_settings(old: dict, new: dict) -> list[tuple[str, str | None, str | None]]`,
  `REDACTED_SETTINGS_KEYS: set[str]`, `format_settings_change_fields(changes: list) -> list[tuple[str, str]]`.
  Used by Task 5's `check_palworld_settings_change`.

- [ ] **Step 1: Add cache state and load/save functions**

Right after the existing block ending in `save_last_release(tag)` in `main.py`:

```python
# ---------- Last Palworld settings snapshot (settings-change alert) ----------
PALWORLD_SETTINGS_CACHE_PATH = "last_palworld_settings.json"
last_palworld_settings = None  # cached in-memory; mirrors last_palworld_settings.json on disk; None until first check


def load_last_palworld_settings():
    global last_palworld_settings
    try:
        with open(PALWORLD_SETTINGS_CACHE_PATH) as f:
            last_palworld_settings = json.load(f)
    except FileNotFoundError:
        last_palworld_settings = None
    except json.JSONDecodeError:
        log.warning("last_palworld_settings.json is corrupt, starting with no cached settings")
        last_palworld_settings = None


def save_last_palworld_settings(settings):
    global last_palworld_settings
    last_palworld_settings = settings
    with open(PALWORLD_SETTINGS_CACHE_PATH, "w") as f:
        json.dump(settings, f, indent=2)
```

- [ ] **Step 2: Add diff and formatting functions**

Directly below the functions from Step 1:

```python
REDACTED_SETTINGS_KEYS = {"AdminPassword", "ServerPassword"}


def diff_palworld_settings(old, new):
    changes = []
    for key in sorted(set(old) | set(new)):
        old_val, new_val = old.get(key), new.get(key)
        if old_val != new_val:
            changes.append((key, old_val, new_val))
    return changes


def format_settings_change_fields(changes):
    fields = []
    for key, old_val, new_val in changes[:25]:
        if key in REDACTED_SETTINGS_KEYS:
            display = "(changed)"
        else:
            display = f"{old_val if old_val is not None else '—'} → {new_val if new_val is not None else '—'}"
        fields.append((key, display))
    if len(changes) > 25:
        fields.append(("…", f"+{len(changes) - 25} more changed (see server config)"))
    return fields
```

- [ ] **Step 3: Verify manually**

```bash
cd /path/to/swee
DISCORD_BOT_TOKEN=x GUILD_ID=1 ADMIN_ROLE_ID=1 STATS_CHANNEL_ID=1 ACTIVITY_CHANNEL_ID=1 \
ALERTS_CHANNEL_ID=1 ADMIN_CHANNEL_ID=1 COMMANDS_CHANNEL_ID=1 BOT_UPDATES_CHANNEL_ID=1 \
REST_HOST=x REST_PORT=1 REST_USER=x REST_PASSWORD=x GITHUB_REPO=x/y \
PALWORLD_SETTINGS_INI_PATH=/tmp/swee-test/sample.ini \
python -c "
from main import diff_palworld_settings, format_settings_change_fields

old = {'ExpRate': '1.000000', 'ServerPassword': '\"old\"', 'Difficulty': 'None'}
new = {'ExpRate': '2.000000', 'ServerPassword': '\"new\"', 'Difficulty': 'None', 'MaxPlayers': '32'}

changes = diff_palworld_settings(old, new)
changed_keys = {c[0] for c in changes}
assert changed_keys == {'ExpRate', 'ServerPassword', 'MaxPlayers'}, changes

fields = format_settings_change_fields(changes)
by_key = dict(fields)
assert by_key['ExpRate'] == '1.000000 → 2.000000', by_key
assert by_key['ServerPassword'] == '(changed)', by_key
assert by_key['MaxPlayers'] == '— → 32', by_key
print('OK', fields)

# 26 changes should truncate to 25 + summary field
big_old = {f'K{i}': 'a' for i in range(26)}
big_new = {f'K{i}': 'b' for i in range(26)}
big_changes = diff_palworld_settings(big_old, big_new)
big_fields = format_settings_change_fields(big_changes)
assert len(big_fields) == 26, len(big_fields)
assert big_fields[-1][0] == '…' and '+1 more' in big_fields[-1][1], big_fields[-1]
print('OK truncation')
"
```

Expected: `OK [...]` then `OK truncation`, no assertion errors.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add settings snapshot cache and diff/format helpers"
```

---

### Task 4: Startup loading

**Files:**
- Modify: `main.py:802-803` (inside `main()`, alongside `load_player_history()`/`load_last_release()`)

**Interfaces:**
- Consumes: `load_last_palworld_settings()` from Task 3.
- Produces: nothing new — just wires an existing function into startup.

- [ ] **Step 1: Call the loader at startup**

In `main()`:

```python
    load_player_history()
    load_last_release()
```

becomes:

```python
    load_player_history()
    load_last_release()
    load_last_palworld_settings()
```

- [ ] **Step 2: Verify manually**

```bash
cd /path/to/swee
DISCORD_BOT_TOKEN=x GUILD_ID=1 ADMIN_ROLE_ID=1 STATS_CHANNEL_ID=1 ACTIVITY_CHANNEL_ID=1 \
ALERTS_CHANNEL_ID=1 ADMIN_CHANNEL_ID=1 COMMANDS_CHANNEL_ID=1 BOT_UPDATES_CHANNEL_ID=1 \
REST_HOST=x REST_PORT=1 REST_USER=x REST_PASSWORD=x GITHUB_REPO=x/y \
PALWORLD_SETTINGS_INI_PATH=/tmp/swee-test/sample.ini \
python -c "
import main
assert main.last_palworld_settings is None
main.load_last_palworld_settings()
assert main.last_palworld_settings is None  # no cache file yet on a clean checkout
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: load Palworld settings snapshot at startup"
```

---

### Task 5: Wire the check into `log_tailer` and post the alert

**Files:**
- Modify: `main.py` — add `check_palworld_settings_change()` near the other `log_tailer`-adjacent
  helpers (right after the `# ---------- Log tailing ----------` section header, before
  `log_tailer()` itself), and modify the `VERSION_RE` branch inside `log_tailer()` (around line
  565-567).

**Interfaces:**
- Consumes: `parse_palworld_settings` (Task 2), `last_palworld_settings`,
  `save_last_palworld_settings`, `diff_palworld_settings`, `format_settings_change_fields`
  (Task 3), `PALWORLD_SETTINGS_INI_PATH` (Task 1), `broadcast_embed`, `ALERTS_CHANNEL_ID`,
  `COLOR_SHUTDOWN`.
- Produces: `check_palworld_settings_change()` — awaited from `log_tailer`.

- [ ] **Step 1: Add `check_palworld_settings_change`**

Add this function directly above `async def log_tailer():`:

```python
async def check_palworld_settings_change():
    global last_palworld_settings
    try:
        new_settings = await asyncio.to_thread(parse_palworld_settings, PALWORLD_SETTINGS_INI_PATH)
    except Exception:
        log.warning("failed to read/parse PalWorldSettings.ini, skipping settings-change check", exc_info=True)
        return

    if last_palworld_settings is None:
        # First-ever check — seed the baseline without announcing, so shipping this
        # feature doesn't dump every existing setting as "changed" on first deploy.
        save_last_palworld_settings(new_settings)
        return

    changes = diff_palworld_settings(last_palworld_settings, new_settings)
    if not changes:
        return

    save_last_palworld_settings(new_settings)
    await broadcast_embed(
        "Palworld settings changed",
        None,
        COLOR_SHUTDOWN,
        channel_id=ALERTS_CHANNEL_ID,
        fields=format_settings_change_fields(changes),
    )
```

- [ ] **Step 2: Call it from the `VERSION_RE` branch**

In `log_tailer()`, change:

```python
                    elif m := VERSION_RE.search(msg):
                        if not _bot_restart_in_progress:
                            await broadcast_embed("Server is online", f"Game version: `{m.group(1)}`", COLOR_READY, dt, channel_id=ALERTS_CHANNEL_ID)
```

to:

```python
                    elif m := VERSION_RE.search(msg):
                        if not _bot_restart_in_progress:
                            await broadcast_embed("Server is online", f"Game version: `{m.group(1)}`", COLOR_READY, dt, channel_id=ALERTS_CHANNEL_ID)
                        await check_palworld_settings_change()
```

This runs the check on every "Game version is..." log line regardless of
`_bot_restart_in_progress`, since the underlying event (server came back online with active
settings) happened either way — `_bot_restart_in_progress` only controls whether the *generic*
"Server is online" embed is suppressed in favor of `restart_palworld`'s own result embed.

- [ ] **Step 3: Verify manually — full first-run-then-change cycle**

```bash
cd /path/to/swee
rm -f /tmp/swee-test/last_palworld_settings.json
cd /tmp/swee-test
DISCORD_BOT_TOKEN=x GUILD_ID=1 ADMIN_ROLE_ID=1 STATS_CHANNEL_ID=1 ACTIVITY_CHANNEL_ID=1 \
ALERTS_CHANNEL_ID=1 ADMIN_CHANNEL_ID=1 COMMANDS_CHANNEL_ID=1 BOT_UPDATES_CHANNEL_ID=1 \
REST_HOST=x REST_PORT=1 REST_USER=x REST_PASSWORD=x GITHUB_REPO=x/y \
PALWORLD_SETTINGS_INI_PATH=/tmp/swee-test/sample.ini \
python -c "
import asyncio, sys
sys.path.insert(0, '/path/to/swee')
import main

async def run():
    # First check: no cache yet -> seeds silently, no broadcast call needed to succeed
    # (bot.get_channel will return None since there's no real bot connection, so
    # broadcast_embed would log a warning if called — assert it ISN'T called on first run).
    assert main.last_palworld_settings is None
    await main.check_palworld_settings_change()
    assert main.last_palworld_settings is not None, 'should have seeded from first check'
    print('seed OK:', main.last_palworld_settings)

    # Second check with no file change -> no-op
    before = dict(main.last_palworld_settings)
    await main.check_palworld_settings_change()
    assert main.last_palworld_settings == before
    print('no-op OK')

asyncio.run(run())
"
```

Expected: `seed OK: {...}` then `no-op OK`, no exceptions. (`broadcast_embed` will log a
`channel not found` warning if reached on a changed run — that's expected here since there's no
live Discord connection; the assertions on `last_palworld_settings` are what confirm correctness.)

- [ ] **Step 4: Verify the change-detected path**

```bash
cat > /tmp/swee-test/sample.ini << 'EOF'
[/Script/Pal.PalGameWorldSettings]
OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,ServerName="My Server, the best",ServerPassword="hunter2",ExpRate=3.000000)
EOF
cd /tmp/swee-test
DISCORD_BOT_TOKEN=x GUILD_ID=1 ADMIN_ROLE_ID=1 STATS_CHANNEL_ID=1 ACTIVITY_CHANNEL_ID=1 \
ALERTS_CHANNEL_ID=1 ADMIN_CHANNEL_ID=1 COMMANDS_CHANNEL_ID=1 BOT_UPDATES_CHANNEL_ID=1 \
REST_HOST=x REST_PORT=1 REST_USER=x REST_PASSWORD=x GITHUB_REPO=x/y \
PALWORLD_SETTINGS_INI_PATH=/tmp/swee-test/sample.ini \
python -c "
import asyncio, sys
sys.path.insert(0, '/path/to/swee')
import main

async def run():
    main.load_last_palworld_settings()  # picks up cache written by the previous step
    before = main.last_palworld_settings
    assert before is not None
    await main.check_palworld_settings_change()
    assert main.last_palworld_settings != before
    assert main.last_palworld_settings['ExpRate'] == '3.000000'
    print('change-detected OK')

asyncio.run(run())
"
rm -rf /tmp/swee-test
```

Expected: `change-detected OK`. (Replace `/path/to/swee` with the actual repo path in both
snippets.)

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: alert on Palworld settings changes after server restart"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md` (add a bullet to the "How it works" list, alongside the existing
  "Unplanned-restart notification" and "RAM auto-restart" bullets)

**Interfaces:** None — documentation only.

- [ ] **Step 1: Add a README bullet**

In the `## How it works` list in `README.md`, after the "Release announcements" bullet, add:

```markdown
- **Settings-change alert** — every time the server comes back online after a restart (planned
  or unplanned), the bot reads `PalWorldSettingsIniPath` from `PALWORLD_SETTINGS_INI_PATH` and
  compares it to the last-seen snapshot (`last_palworld_settings.json`). Any added, removed, or
  changed setting posts an embed to `ALERTS_CHANNEL_ID` listing each change as `Old → New`;
  `AdminPassword`/`ServerPassword` changes show as `(changed)` rather than the real values. The
  first check after a fresh deploy seeds the baseline silently instead of alerting.
```

(Fix the stray `PalWorldSettingsIniPath` phrase — it should just read "reads
`PALWORLD_SETTINGS_INI_PATH`", not restate a made-up key name.)

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document the Palworld settings-change alert"
```

---

## Final Integration Check

After all 6 tasks are committed, do one end-to-end sanity check before opening the PR:

```bash
cd /path/to/swee
python -m py_compile main.py && echo "syntax OK"
```

Then push the feature branch and open a PR per `CLAUDE.md` (never push directly to `main`).
