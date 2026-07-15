# Config view/edit commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/config list`, `/config get`, and `/config set` slash commands so admins can view and
edit `PalWorldSettings.ini` from Discord instead of SSHing into the host.

**Architecture:** Extend `swee/palworld_settings.py` (already parses the ini for the
settings-change alert) with a writer and value-validation layer, then build a new
`swee/config_commands.py` module with three admin-only slash commands on an `app_commands.Group`,
one of which (`/config list`) uses a `discord.ui.View` for Prev/Next pagination — the bot's first
use of buttons.

**Tech Stack:** Python 3.14, discord.py (existing `app_commands`/`discord.ui`), stdlib `unittest`
for the new pure-function tests (no new dependency — this repo has no test runner yet, so this
plan also wires up `python -m unittest` as one and documents it in `CLAUDE.md`).

## Global Constraints

- No new entries in `requirements.txt` — everything needed (`unittest`) is stdlib.
- `AdminPassword`/`ServerPassword` (`REDACTED_SETTINGS_KEYS` in `swee/palworld_settings.py`) must
  never be readable or settable through any `/config` subcommand.
- All three subcommands are admin-only via the existing `is_admin()` (`swee/bot.py`) — requires
  `ADMIN_ROLE_ID` and must run in `ADMIN_CHANNEL_ID`.
- `/config list` and `/config get` reply ephemeral; `/config set` replies non-ephemeral (visible to
  other admins), and never restarts the server itself — only reminds the user to run `/restart`.
- `/config set` only modifies keys that already exist in the ini; it never adds new keys.
- Category-switching value writes (e.g. a bool string over a numeric setting) are always rejected.
- Pagination: 20 settings per page, 180-second view timeout, paging restricted to the invoking
  user.

---

## File Structure

- Modify: `swee/palworld_settings.py` — add `render_option_settings`, `write_palworld_setting`,
  `visible_settings`, `classify_value`, `format_new_value`
- Create: `tests/__init__.py` (empty, makes `tests` a package for `unittest discover`)
- Create: `tests/test_palworld_settings.py` — unit tests for all new `palworld_settings.py`
  functions
- Create: `swee/config_commands.py` — the `config` command group, autocomplete callback, and
  `ConfigListView`
- Modify: `main.py` — import `swee.config_commands`
- Modify: `README.md` — document the new commands
- Modify: `CLAUDE.md` — replace the "no automated tests" line with the real test command

---

### Task 1: Ini writer and redaction helper

**Files:**
- Modify: `swee/palworld_settings.py`
- Create: `tests/__init__.py`
- Create: `tests/test_palworld_settings.py`

**Interfaces:**
- Consumes: existing `OPTION_SETTINGS_RE`, `_parse_option_settings`, `parse_palworld_settings`,
  `REDACTED_SETTINGS_KEYS` (all already defined in `swee/palworld_settings.py`)
- Produces:
  - `render_option_settings(pairs: dict[str, str]) -> str`
  - `write_palworld_setting(path: str, key: str, formatted_value: str) -> None`
  - `visible_settings(path: str) -> dict[str, str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/__init__.py` (empty file).

Create `tests/test_palworld_settings.py`:

```python
import os
import tempfile
import unittest

from swee.palworld_settings import (
    parse_palworld_settings,
    render_option_settings,
    visible_settings,
    write_palworld_setting,
)

SAMPLE_INI = (
    '[/Script/Pal.PalGameWorldSettings]\n'
    'OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,'
    'ServerName="My Server",bIsPvP=False,'
    'AdminPassword="secret",ServerDescription="Hello, world")\n'
)


class RenderOptionSettingsTests(unittest.TestCase):
    def test_round_trips_parsed_pairs(self):
        pairs = {"Difficulty": "None", "DayTimeSpeedRate": "1.000000", "ServerName": '"My Server"'}
        self.assertEqual(
            render_option_settings(pairs),
            'Difficulty=None,DayTimeSpeedRate=1.000000,ServerName="My Server"',
        )


class WritePalworldSettingTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        with open(self.path, "w") as f:
            f.write(SAMPLE_INI)

    def tearDown(self):
        os.remove(self.path)

    def test_updates_only_target_key(self):
        write_palworld_setting(self.path, "bIsPvP", "True")
        pairs = parse_palworld_settings(self.path)
        self.assertEqual(pairs["bIsPvP"], "True")
        self.assertEqual(pairs["Difficulty"], "None")
        self.assertEqual(pairs["ServerName"], '"My Server"')
        self.assertEqual(pairs["ServerDescription"], '"Hello, world"')

    def test_preserves_surrounding_file_content(self):
        write_palworld_setting(self.path, "Difficulty", "Hard")
        with open(self.path) as f:
            content = f.read()
        self.assertTrue(content.startswith("[/Script/Pal.PalGameWorldSettings]\n"))
        self.assertTrue(content.endswith("\n"))


class VisibleSettingsTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        with open(self.path, "w") as f:
            f.write(SAMPLE_INI)

    def tearDown(self):
        os.remove(self.path)

    def test_omits_redacted_keys(self):
        settings = visible_settings(self.path)
        self.assertNotIn("AdminPassword", settings)
        self.assertEqual(settings["Difficulty"], "None")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_palworld_settings -v`
Expected: `ImportError`/`AttributeError` — `render_option_settings`, `write_palworld_setting`,
`visible_settings` don't exist yet.

- [ ] **Step 3: Implement the three functions**

Add to `swee/palworld_settings.py` (after `diff_palworld_settings`, before
`format_settings_change_fields`):

```python
def render_option_settings(pairs):
    return ",".join(f"{k}={v}" for k, v in pairs.items())


def write_palworld_setting(path, key, formatted_value):
    with open(path) as f:
        content = f.read()
    m = OPTION_SETTINGS_RE.search(content)
    if not m:
        raise ValueError(f"no OptionSettings line found in {path}")
    pairs = _parse_option_settings(m.group(1))
    pairs[key] = formatted_value
    new_inner = render_option_settings(pairs)
    new_content = content[:m.start(1)] + new_inner + content[m.end(1):]
    with open(path, "w") as f:
        f.write(new_content)


def visible_settings(path):
    return {k: v for k, v in parse_palworld_settings(path).items() if k not in REDACTED_SETTINGS_KEYS}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_palworld_settings -v`
Expected: `OK` (4 tests)

- [ ] **Step 5: Commit**

```bash
git add swee/palworld_settings.py tests/__init__.py tests/test_palworld_settings.py
git commit -m "feat: add ini writer and redaction helper for Palworld settings"
```

---

### Task 2: Value classification and validation

**Files:**
- Modify: `swee/palworld_settings.py`
- Modify: `tests/test_palworld_settings.py`

**Interfaces:**
- Consumes: nothing new (pure string logic)
- Produces:
  - `classify_value(value: str) -> str` — one of `"bool"`, `"number"`, `"string"`, `"token"`
  - `format_new_value(current_value: str, raw_input: str) -> str` — raises `ValueError` on
    invalid/category-mismatched input, otherwise returns the on-disk formatted value

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_palworld_settings.py` (add these imports to the existing `from
swee.palworld_settings import (...)` block: `classify_value`, `format_new_value` — alphabetical,
so the full import becomes):

```python
from swee.palworld_settings import (
    classify_value,
    format_new_value,
    parse_palworld_settings,
    render_option_settings,
    visible_settings,
    write_palworld_setting,
)
```

Append these test classes to the end of the file (before the `if __name__ == "__main__":` block):

```python
class ClassifyValueTests(unittest.TestCase):
    def test_bool(self):
        self.assertEqual(classify_value("True"), "bool")
        self.assertEqual(classify_value("False"), "bool")

    def test_number(self):
        self.assertEqual(classify_value("1.000000"), "number")
        self.assertEqual(classify_value("-5"), "number")

    def test_string(self):
        self.assertEqual(classify_value('"My Server"'), "string")

    def test_token(self):
        self.assertEqual(classify_value("None"), "token")


class FormatNewValueTests(unittest.TestCase):
    def test_bool_accepts_case_insensitive(self):
        self.assertEqual(format_new_value("False", "true"), "True")
        self.assertEqual(format_new_value("True", "FALSE"), "False")

    def test_bool_rejects_non_bool(self):
        with self.assertRaises(ValueError):
            format_new_value("True", "1")

    def test_number_accepts_number(self):
        self.assertEqual(format_new_value("1.000000", "2.5"), "2.5")

    def test_number_rejects_non_number(self):
        with self.assertRaises(ValueError):
            format_new_value("1.000000", "abc")

    def test_string_wraps_in_quotes(self):
        self.assertEqual(format_new_value('"My Server"', "New Name"), '"New Name"')

    def test_string_rejects_embedded_quote(self):
        with self.assertRaises(ValueError):
            format_new_value('"My Server"', 'bad "name"')

    def test_token_accepts_bare_word(self):
        self.assertEqual(format_new_value("None", "Hard"), "Hard")

    def test_token_rejects_spaces(self):
        with self.assertRaises(ValueError):
            format_new_value("None", "not valid")

    def test_category_switch_rejected(self):
        with self.assertRaises(ValueError):
            format_new_value("1.000000", "True")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_palworld_settings -v`
Expected: `ImportError` — `classify_value`/`format_new_value` don't exist yet.

- [ ] **Step 3: Implement the two functions**

Add to `swee/palworld_settings.py`, right after the `OPTION_SETTINGS_RE`/`REDACTED_SETTINGS_KEYS`
constants near the top of the file:

```python
NUMBER_RE = re.compile(r'^-?\d+(\.\d+)?$')
```

Add the functions themselves after `render_option_settings`/`write_palworld_setting` (order in
the file doesn't matter functionally, but keep writer functions grouped together):

```python
def classify_value(value):
    if value in ("True", "False"):
        return "bool"
    if NUMBER_RE.match(value):
        return "number"
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return "string"
    return "token"


def format_new_value(current_value, raw_input):
    category = classify_value(current_value)
    stripped = raw_input.strip()

    if category == "bool":
        lowered = stripped.lower()
        if lowered not in ("true", "false"):
            raise ValueError(f'`{current_value}` is a True/False setting — got {raw_input!r}')
        return "True" if lowered == "true" else "False"

    if category == "number":
        if not NUMBER_RE.match(stripped):
            raise ValueError(f"`{current_value}` is a numeric setting — got {raw_input!r}")
        return stripped

    if category == "string":
        if '"' in raw_input:
            raise ValueError('value cannot contain a literal `"` character')
        return f'"{raw_input}"'

    # token
    if any(c in raw_input for c in ' ,"()'):
        raise ValueError(
            f"expected a plain value with no spaces, commas, quotes, or parens — got {raw_input!r}"
        )
    return raw_input
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_palworld_settings -v`
Expected: `OK` (14 tests total)

- [ ] **Step 5: Commit**

```bash
git add swee/palworld_settings.py tests/test_palworld_settings.py
git commit -m "feat: add value classification and validation for Palworld settings"
```

---

### Task 3: `config` command group and `/config get`

**Files:**
- Create: `swee/config_commands.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: `swee.bot.bot`, `swee.bot.is_admin`, `swee.config.PALWORLD_SETTINGS_INI_PATH`,
  `swee.palworld_settings.{REDACTED_SETTINGS_KEYS, parse_palworld_settings, visible_settings}`
  (`visible_settings`/`REDACTED_SETTINGS_KEYS` from Task 1)
- Produces: `config_group` (`app_commands.Group`, registered on `bot.tree`), `_key_autocomplete`
  (reused by Task 5's `/config set`)

- [ ] **Step 1: Create the module with the group, autocomplete, and `/config get`**

Create `swee/config_commands.py`:

```python
import logging

import discord
from discord import app_commands

from swee.bot import bot, is_admin
from swee.config import PALWORLD_SETTINGS_INI_PATH
from swee.palworld_settings import REDACTED_SETTINGS_KEYS, parse_palworld_settings, visible_settings

log = logging.getLogger("swee")

PAGE_SIZE = 20

config_group = app_commands.Group(name="config", description="View and edit Palworld server settings")


async def _key_autocomplete(interaction: discord.Interaction, current: str):
    try:
        keys = visible_settings(PALWORLD_SETTINGS_INI_PATH).keys()
    except Exception:
        log.exception("config autocomplete: failed to read server settings")
        return []
    matches = [k for k in keys if current.lower() in k.lower()]
    return [app_commands.Choice(name=k, value=k) for k in matches[:25]]


@config_group.command(name="get", description="Show a single Palworld server setting")
@app_commands.describe(key="Setting name")
@app_commands.autocomplete(key=_key_autocomplete)
@is_admin()
async def config_get(interaction: discord.Interaction, key: str):
    if key in REDACTED_SETTINGS_KEYS:
        await interaction.response.send_message(
            f"`{key}` can only be edited directly on the server.", ephemeral=True
        )
        return
    try:
        settings = parse_palworld_settings(PALWORLD_SETTINGS_INI_PATH)
    except Exception:
        log.exception("/config get: failed to read server settings")
        await interaction.response.send_message("Couldn't read server settings.", ephemeral=True)
        return
    if key not in settings:
        await interaction.response.send_message(f"No such setting: `{key}`", ephemeral=True)
        return
    await interaction.response.send_message(f"`{key}` = `{settings[key]}`", ephemeral=True)


bot.tree.add_command(config_group)
```

- [ ] **Step 2: Wire the module into startup**

In `main.py`, add the import alongside the existing `swee.commands` import:

```python
import swee.commands  # noqa: F401 — registers slash commands via decorator side effects
import swee.config_commands  # noqa: F401 — registers slash commands via decorator side effects
```

- [ ] **Step 3: Manually verify**

There's no automated test for the command layer (no Discord test harness in this repo — matches
the existing pattern where `swee/commands.py` also has no tests). Verify manually:

1. Run `python -m py_compile swee/config_commands.py main.py` — confirms no syntax errors.
   Expected: exits with no output/error.
2. If you have a running bot pointed at a real Palworld server: run `/config get key:Difficulty`
   in the admin channel and confirm it replies ephemerally with the current value. Try a
   redacted key (`/config get key:AdminPassword`) and confirm it's rejected. Try a nonexistent
   key and confirm the "No such setting" message.

- [ ] **Step 4: Commit**

```bash
git add swee/config_commands.py main.py
git commit -m "feat: add /config get command"
```

---

### Task 4: `/config list` with pagination

**Files:**
- Modify: `swee/config_commands.py`

**Interfaces:**
- Consumes: `PAGE_SIZE`, `visible_settings` (Task 1/3), `is_admin`, `bot`, `config_group`
- Produces: `ConfigListView` (`discord.ui.View` subclass), `/config list` command

- [ ] **Step 1: Add `ConfigListView` and the `/config list` command**

Add to `swee/config_commands.py`, after the `_key_autocomplete` function and before
`config_get`:

```python
class ConfigListView(discord.ui.View):
    def __init__(self, user_id, entries, page):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.entries = entries
        self.page = page
        self.last_page = (len(entries) - 1) // PAGE_SIZE
        self.message = None
        self._update_buttons()

    def _update_buttons(self):
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.last_page

    def embed(self):
        start = self.page * PAGE_SIZE
        embed = discord.Embed(title=f"Palworld settings (page {self.page + 1}/{self.last_page + 1})")
        for key, value in self.entries[start:start + PAGE_SIZE]:
            embed.add_field(name=key, value=value, inline=False)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran this command can page through it.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        self.previous_button.disabled = True
        self.next_button.disabled = True
        if self.message is not None:
            await self.message.edit(view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)


@config_group.command(name="list", description="List Palworld server settings")
@app_commands.describe(page="Page number (starts at 1)")
@is_admin()
async def config_list(interaction: discord.Interaction, page: int = 1):
    try:
        settings = visible_settings(PALWORLD_SETTINGS_INI_PATH)
    except Exception:
        log.exception("/config list: failed to read server settings")
        await interaction.response.send_message("Couldn't read server settings.", ephemeral=True)
        return
    entries = sorted(settings.items())
    last_page = (len(entries) - 1) // PAGE_SIZE
    zero_page = max(0, min(page - 1, last_page))
    view = ConfigListView(interaction.user.id, entries, zero_page)
    await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)
    view.message = await interaction.original_response()
```

- [ ] **Step 2: Manually verify**

1. Run `python -m py_compile swee/config_commands.py` — expected: no output/error.
2. Against a running bot: run `/config list`, confirm the first page shows up to 20 settings,
   `Previous` is disabled on page 1, `Next` works and shows the next 20, and paging stops
   responding to clicks from a different user (test with a second Discord account if available,
   otherwise skip). Confirm neither `AdminPassword` nor `ServerPassword` appear anywhere in the
   list.

- [ ] **Step 3: Commit**

```bash
git add swee/config_commands.py
git commit -m "feat: add /config list command with pagination"
```

---

### Task 5: `/config set` and docs

**Files:**
- Modify: `swee/config_commands.py`
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `format_new_value`, `write_palworld_setting` (Task 2/1), `_key_autocomplete`,
  `REDACTED_SETTINGS_KEYS`, `parse_palworld_settings`
- Produces: `/config set` command (final piece — no further consumers)

- [ ] **Step 1: Add the `/config set` command**

Add to `swee/config_commands.py`. First, update the import line to pull in the two remaining
functions:

```python
from swee.palworld_settings import (
    REDACTED_SETTINGS_KEYS,
    format_new_value,
    parse_palworld_settings,
    visible_settings,
    write_palworld_setting,
)
```

Then add the command at the end of the file:

```python
@config_group.command(name="set", description="Change a Palworld server setting (requires /restart to apply)")
@app_commands.describe(key="Setting name", value="New value")
@app_commands.autocomplete(key=_key_autocomplete)
@is_admin()
async def config_set(interaction: discord.Interaction, key: str, value: str):
    if key in REDACTED_SETTINGS_KEYS:
        await interaction.response.send_message(
            f"`{key}` can only be edited directly on the server.", ephemeral=True
        )
        return
    try:
        settings = parse_palworld_settings(PALWORLD_SETTINGS_INI_PATH)
    except Exception:
        log.exception("/config set: failed to read server settings")
        await interaction.response.send_message("Couldn't read server settings.", ephemeral=True)
        return
    if key not in settings:
        await interaction.response.send_message(f"No such setting: `{key}`", ephemeral=True)
        return
    try:
        formatted = format_new_value(settings[key], value)
    except ValueError as e:
        await interaction.response.send_message(str(e), ephemeral=True)
        return
    try:
        write_palworld_setting(PALWORLD_SETTINGS_INI_PATH, key, formatted)
    except Exception:
        log.exception("/config set: failed to write server settings")
        await interaction.response.send_message("Couldn't write server settings.", ephemeral=True)
        return
    await interaction.response.send_message(f"`{key}` set to `{formatted}`. Run `/restart` to apply.")
```

- [ ] **Step 2: Manually verify**

1. Run `python -m unittest discover tests -v` — expected: `OK` (14 tests, confirms Task 1/2
   functions this command depends on still pass).
2. Run `python -m py_compile swee/config_commands.py` — expected: no output/error.
3. Against a running bot pointed at a test server: run `/config set key:Difficulty value:Hard`,
   confirm the non-ephemeral confirmation message and reminder to `/restart`. Confirm the ini file
   on disk actually changed (only that key). Try setting a bool key to a non-bool value and
   confirm the rejection message. Try `/config set key:AdminPassword value:x` and confirm it's
   blocked.

- [ ] **Step 3: Update README**

In `README.md`, change:

```
Slash commands are synced to `GUILD_ID` on startup. Admin-only commands (`save`, `kick`, `ban`,
`broadcast`, `restart`) require `ADMIN_ROLE_ID`. `restart` and the RAM reader shell out to
```

to:

```
Slash commands are synced to `GUILD_ID` on startup. Admin-only commands (`save`, `kick`, `ban`,
`broadcast`, `restart`, `config list`, `config get`, `config set`) require `ADMIN_ROLE_ID`.
`config set` edits `PALWORLD_SETTINGS_INI_PATH` directly and does not itself restart the
server — run `restart` afterward to apply the change. `restart` and the RAM reader shell out to
```

Also add a bullet under "How it works", after the existing "Settings-change alert" bullet:

```
- **Config view/edit** — `/config list` (paginated) and `/config get <key>` show current values
  from `PALWORLD_SETTINGS_INI_PATH`; `/config set <key> <value>` writes a new value to that file.
  `AdminPassword`/`ServerPassword` can't be read or set through the bot. Like any ini edit, a
  change made via `/config set` only takes effect after the next `restart`.
```

- [ ] **Step 4: Update CLAUDE.md**

In `CLAUDE.md`, change:

```
- There are no automated tests or test runner configured yet
```

to:

```
- `tests/test_palworld_settings.py` covers the pure ini-parsing/writing/validation functions in
  `swee/palworld_settings.py`; run with `python -m unittest discover tests -v`. No coverage of the
  Discord command layer itself (no test harness for that yet) — verify those manually.
```

- [ ] **Step 5: Commit**

```bash
git add swee/config_commands.py README.md CLAUDE.md
git commit -m "feat: add /config set command; document config commands and test runner"
```
