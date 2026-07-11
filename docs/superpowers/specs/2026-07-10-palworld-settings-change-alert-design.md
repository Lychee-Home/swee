# Palworld settings change alert — design

## Problem

`PalWorldSettings.ini` (the dedicated server's config file) can be edited outside the bot's
knowledge — directly on the host, or via other tooling. Admins have no visibility into when
settings drift from what they expect. When the server restarts (the point settings actually take
effect), the bot should notice if the file changed since last time and post an alert.

## Config

New required env var:

- `PALWORLD_SETTINGS_INI_PATH` — absolute path to `PalWorldSettings.ini`. No default; matches how
  `REST_HOST`/`REST_PORT`/etc. are handled (`os.environ[...]`, fails fast at startup if unset).

## Parsing

Palworld's `PalWorldSettings.ini` has one relevant line:

```
OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,ServerName="My Server",...)
```

A single key (`OptionSettings`) whose value is a parenthesized, comma-separated list of
`Key=Value` pairs. Values are either bare tokens (numbers, enum names, `True`/`False`) or
double-quoted strings that may themselves contain commas (e.g. `ServerDescription="Hello, world"`).

New function `parse_palworld_settings(path) -> dict[str, str]`:
- Reads the file, locates the `OptionSettings=(...)` line.
- Splits the inner content into `Key=Value` pairs, respecting quoted strings (commas inside quotes
  don't split; a hand-rolled scanner rather than `csv`/`re.split`, since values can contain `=`
  inside quotes too, e.g. a password).
- Returns a flat `{key: raw_value_string}` dict. Values are kept as their raw string
  representation (not coerced to float/bool) since we only ever compare-and-display them, never
  compute with them.
- Runs on a thread via `asyncio.to_thread` (matches the existing `_read_last_lines` pattern used
  for `unattended-upgrades.log`).

If the file doesn't exist, is unreadable, or doesn't contain a parseable `OptionSettings` line,
the function raises; callers catch and log a warning, skipping the check for that cycle.

## Snapshot cache

`last_palworld_settings.json` — the last-seen parsed dict, stored flat as `{key: value}`.

- Loaded at startup via `load_last_palworld_settings()`, sibling to the existing
  `load_player_history()` / `load_last_release()` loaders, called from `main()`.
- On first-ever run (no cache file), the current settings are parsed and saved as the baseline
  with **no alert posted** — mirrors `last_release.json`'s seed-without-announcing behavior, so
  deploying this feature doesn't immediately spam every existing setting as "changed."
- After every successful diff (changed or not), the cache is updated to the latest parsed
  snapshot.

## Trigger point

Hooked into the existing `VERSION_RE` branch in `log_tailer()` — the "Server is online" event,
which already fires after any restart (planned via `/restart`/RAM auto-restart, or unplanned via
crash/host reboot/package upgrade). This is the point the server has actually come back up with
whatever settings are now active.

Sequence in that branch, after the existing "Server is online" embed is posted:

1. Parse the ini (`asyncio.to_thread`), wrapped in try/except — on failure, log a warning and
   return (never blocks the "Server is online" post, never crashes `log_tailer`).
2. Diff against the cached snapshot (dict key/value comparison — added, removed, and
   changed-value keys all count as a change).
3. If no cached snapshot exists yet: save the parsed dict as the new baseline, no alert.
4. If there's no diff: nothing further happens.
5. If there's a diff: save the new snapshot, then post an embed to `ALERTS_CHANNEL_ID`.

## Alert embed

Title: "Palworld settings changed". One field per changed key, value formatted `Old → New`
(added keys show `— → New`; removed keys show `Old → —`). Discord embeds cap at 25 fields — if
more than 25 keys changed, show the first 25 and append a final field noting "+N more changed
(see server config)".

`AdminPassword` and `ServerPassword` are special-cased: if either is among the changed keys, the
field still appears (so admins know a password rotated) but the value is rendered as `(changed)`
instead of the real old/new strings, to avoid leaking secrets into Discord.

Color: reuse `COLOR_SHUTDOWN` (the existing alerts-channel warning color) for consistency with
other `ALERTS_CHANNEL_ID` posts.

## Error handling

Same shape as `CAUSE_DETECTORS` / `detect_unattended_upgrades`: any exception during parse, diff,
or file I/O is caught, logged (`log.exception`/`log.warning`), and the check is skipped for that
cycle — it never takes down `log_tailer`'s main loop or blocks the "Server is online" alert that
already exists.

## Out of scope

- No slash command to manually trigger a check or view current settings (could be a follow-up).
- No validation of setting values (e.g. flagging an out-of-range `ExpRate`) — purely change
  detection.
- No handling of comments or multi-line ini structure beyond the single `OptionSettings` line,
  since that's the only line Palworld's dedicated server actually writes.

## Testing

No test suite exists in this repo yet. Verification will be manual: construct a sample
`PalWorldSettings.ini`, run the parser against it directly, edit a value, and confirm the diff
produces the expected changed-keys set — plus a manual end-to-end check against a real server if
available.
