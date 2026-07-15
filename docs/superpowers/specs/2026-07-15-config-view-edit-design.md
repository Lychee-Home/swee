# View and edit Palworld settings via Discord — design

## Problem

`swee/palworld_settings.py` already parses `PalWorldSettings.ini`'s `OptionSettings=(...)` line
into a `{key: value}` dict, but only for the read-only settings-change alert. There's no way for
an admin to view or change a setting without SSHing into the host and hand-editing the ini. This
adds slash commands to do both from Discord.

There is no REST endpoint for reading or writing server settings — Palworld's REST API only
exposes runtime info/players/metrics and action endpoints (save/kick/ban/announce). Any
modification has to edit the ini file directly, and — like any ini edit — won't take effect until
the Palworld service restarts.

## Commands

New `app_commands.Group` named `config`, admin-only (`is_admin()`, same as `/save`/`/kick`/etc. —
requires `ADMIN_ROLE_ID` and must run in `ADMIN_CHANNEL_ID`):

- `/config list [page]` — paginated view of all settings. Ephemeral (matches `/status`'s
  look-something-up pattern). Defaults to page 1.
- `/config get <key>` — a single setting's current value. Ephemeral. `key` uses
  `app_commands.autocomplete` sourced from the live-parsed ini's keys.
- `/config set <key> <value>` — writes a new value to the ini. **Not** ephemeral — like
  `/save`/`/kick`/`/ban`, other admins in the channel should see that a config value changed.
  Replies with a confirmation that includes a reminder that the change needs `/restart` to take
  effect. Does not restart the server itself.

`AdminPassword` and `ServerPassword` are blocked entirely by all three subcommands: excluded from
the autocomplete list, and rejected with an explicit "edit these directly on the server" error if
typed manually. This keeps Discord out of the credential-handling path (matches the existing
`REDACTED_SETTINGS_KEYS` treatment in the settings-change alert, but stricter — no display at
all rather than a masked value).

## File layout

New module `swee/config_commands.py` (imported from `main.py` next to `swee.commands`, same
decorator-side-effect registration pattern):

- The three `config` subcommands and their autocomplete callback
- `ConfigListView(discord.ui.View)` — the pagination controls for `/config list`

Kept separate from `swee/commands.py` because that file is currently thin REST-call wrappers,
while this feature carries real logic (ini parsing/writing, value validation, a stateful `View`).

New functions in `swee/palworld_settings.py` (extends the existing parser rather than
duplicating it):

- `render_option_settings(pairs: dict[str, str]) -> str` — inverse of `_parse_option_settings`:
  joins an ordered `{key: value}` dict back into `Key=Value,Key=Value,...`. Values are expected to
  already be in their on-disk form (quotes included for strings), matching what
  `_parse_option_settings` produces.
- `write_palworld_setting(path, key, formatted_value)` — reads the file, re-parses the
  `OptionSettings=(...)` line, replaces one key's value in the ordered dict, re-renders it, and
  splices the result back into the original file content (everything outside that one line is
  untouched, byte for byte). Raises the same way `parse_palworld_settings` does if the line isn't
  found.
- `classify_value(value: str) -> str` — categorizes an on-disk value as one of `"bool"`
  (`True`/`False`), `"number"` (matches `^-?\d+(\.\d+)?$`), `"string"` (quoted), or `"token"`
  (anything else — bare enum-like identifiers such as `Difficulty=None`).
- `format_new_value(current_value: str, raw_input: str) -> str` — validates `raw_input` (the raw
  Discord option text) against `classify_value(current_value)`'s category and returns the on-disk
  form, or raises `ValueError` with a user-facing message:
  - `bool`: case-insensitive `true`/`false` → normalized to `True`/`False`; anything else rejected.
  - `number`: must parse as `int` or `float` via the same regex as `classify_value`; stored as
    given text.
  - `string`: any text without a literal `"` (which would break the quoted-value format) gets
    wrapped in quotes; text containing `"` is rejected.
  - `token`: any text with no spaces, commas, quotes, or parens (would break the
    comma-separated/parenthesized format); rejected otherwise.
  - Category-switching (e.g. writing `"True"` over a `number` value) is always rejected — it's far
    more likely a mistake than an intentional type change, and Palworld's ini format has no schema
    to consult to know otherwise.

`/config set` only ever modifies an existing key — there's no path to add a new key, since that'd
require guessing at a type/category with nothing to validate against.

## `/config list` pagination

`ConfigListView` — Previous/Next buttons, ~20 settings per page (comfortably under the 25-field
embed limit), title shows `Page X/Y`. `AdminPassword`/`ServerPassword` are omitted from the listed
keys entirely. Buttons disable at the first/last page. `interaction_check` restricts paging to the
user who ran the command (consistent with it being an ephemeral, personal-lookup response).
180-second timeout, after which the view edits itself to disable both buttons (avoids a
dead button that errors on click after Discord invalidates old interaction tokens).

This is the first use of `discord.ui.View`/buttons in the bot — no existing pattern to match, but
kept minimal (two buttons, no selects/modals) to avoid over-building for a first use case.

## Error handling

- Ini read/parse failures (missing file, no `OptionSettings` line) — caught in each subcommand,
  replied with a generic "couldn't read server settings" ephemeral error, logged via
  `log.exception`. Same shape as how `commands.py`'s existing `on_app_command_error` handles REST
  failures, but handled inline here since these aren't REST calls and don't want to fall through
  to that generic httpx-focused handler.
- `format_new_value` validation errors surface directly as the (ephemeral) command response text —
  no logging needed, these are expected user-input mistakes, not bugs.
- Ini *write* failures (permissions, disk full, etc.) — caught, logged with `log.exception`,
  replied with a generic "couldn't write server settings" error. The read-then-write in
  `write_palworld_setting` is not transactional; a failure partway through (unlikely — it's a
  single `open(...).write()` after the read) would be visible on next `/config get`/`list` rather
  than silently lost.

## Interaction with the existing settings-change alert

No special-casing needed. `/config set` only touches the ini file; the existing alert
(`swee/palworld_settings.py` diff against `last_palworld_settings.json`, checked on the next
"Server is online" event) will pick up bot-made edits exactly the same way it picks up manual
ones, whenever the server is next restarted.

## Out of scope

- No automatic or offered restart from `/config set` — restart is a separate, explicit action via
  the existing `/restart` command.
- No full schema of every `PalWorldSettings.ini` key's valid type/range — category-based
  validation (bool/number/string/token) catches the common mistakes without hardcoding and
  maintaining a schema for ~90 settings as Palworld adds more over time.
- No support for adding brand-new keys not already present in the ini.

## Testing

No test suite exists in this repo yet. Verification will be manual: construct a sample
`PalWorldSettings.ini`, exercise `render_option_settings`/`write_palworld_setting`/
`classify_value`/`format_new_value` directly against it and confirm round-tripping and validation
behave as expected, then a manual end-to-end check of `/config list`/`get`/`set` against a real
bot/server if available.
