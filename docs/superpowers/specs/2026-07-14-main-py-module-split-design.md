# Split main.py into a swee/ package — design

## Problem

`main.py` has grown to ~980 lines and now mixes a dozen unrelated responsibilities in one file:
env/config loading, PalWorldSettings.ini parsing, the Palworld REST client, GitHub release
fetching, RAM reading, Discord embed formatting, player-history persistence, the live stats
embed, unplanned-restart cause detection, journalctl log tailing, service restart, slash
commands, and process wiring. It's already hard to hold in context at once, and every new
feature (see the steady stream of `docs/superpowers/specs/` entries) adds more to the same file.

## Scope

Pure structural refactor: move existing code into a `swee/` package, one module per
responsibility, with **no behavior change**. Any design-smell cleanup (e.g. the module-level
mutable globals for `stats_message_id`, `player_history`, `_bot_restart_in_progress`) is
explicitly out of scope — a candidate for a future follow-up, not this PR.

`main.py` stays at the repo root, since `deploy/swee.service` invokes it directly
(`ExecStart=.../python .../main.py`). It becomes a thin composition root.

## Package layout

```
swee/
  __init__.py
  config.py            # env vars + derived constants (IDs, REST base/auth, thresholds, colors)
  bot.py                # bot instance, intents, is_admin/in_commands_channel checks
  rest_client.py        # PalRestClient + `rest` singleton
  palworld_settings.py  # PalWorldSettings.ini parsing + diff/format helpers
  ram.py                # read_ram_stats, get_ram_usage, should_auto_restart
  embeds.py             # broadcast_embed + stats-embed formatting helpers
  player_history.py     # player_history.json persistence + join/leave/refresh tracking
  releases.py           # GitHub release fetch, note formatting, last_release.json, release_ticker
  restart.py            # check_palworld_service, restart_palworld, auto_restart_sequence,
                         # and the shared _bot_restart_in_progress flag
  cause_detection.py    # unattended-upgrades + ini-diff detectors, registry, detect_unplanned_restart_cause
  log_tailer.py         # journalctl tailing loop + join/leave/shutdown/version parsing
  stats.py              # stats_message_id state, update_stats_message, stats_ticker
  commands.py           # all slash commands (/status, /players, /save, /kick, /ban, /broadcast, /restart)
main.py                 # composition root: logging setup, load persisted state, on_ready/on_message,
                         # start background tasks, asyncio.run entrypoint
```

### Per-module contents (mapped from current `main.py` line ranges)

- **`config.py`**: `load_dotenv()` call, all `os.environ[...]` / `os.environ.get(...)` reads and
  their derived constants (`GUILD_ID` … `OFFLINE_PLAYERS_LIMIT`), `PACIFIC`, `COLOR_*` constants.
- **`bot.py`**: `intents`, `bot = commands.Bot(...)`, `is_admin()`, `in_commands_channel()`. Only
  depends on `config` and `discord` — a leaf module every other module can import without cycles.
- **`rest_client.py`**: `PalRestClient` class + `rest = PalRestClient()` singleton. Depends on
  `config` (`REST_BASE`, `REST_AUTH`).
- **`palworld_settings.py`**: `_parse_option_settings`, `parse_palworld_settings`,
  `REDACTED_SETTINGS_KEYS`, `diff_palworld_settings`, `format_settings_change_fields`,
  `OPTION_SETTINGS_RE`. Pure — no dependency on other `swee` modules.
- **`ram.py`**: `read_ram_stats`, `get_ram_usage`, `should_auto_restart`. Depends only on
  `config` (thresholds).
- **`embeds.py`**: `broadcast_embed`, `build_stats_embed`, `add_status_fields`,
  `format_online_field`, `format_offline_field`, `offline_entries_from_history`. Depends on
  `bot` (`bot.get_channel`), `config` (colors, channel IDs).
- **`player_history.py`**: `PLAYER_HISTORY_PATH`, `player_history`/`online_players`/
  `session_started` state, `load_player_history`, `save_player_history`, `record_join`,
  `record_leave`, `refresh_online_players`. Depends on `rest_client`, `config` (`PACIFIC`).
- **`releases.py`**: `LAST_RELEASE_PATH`, `last_release_tag` state, `load_last_release`,
  `save_last_release`, `fetch_latest_release`, `humanize_release_notes`,
  `RELEASE_NOTE_RE`/`RELEASE_NOTE_LABELS`/`RELEASE_NOTE_SECTION_ORDER`, `release_ticker`.
  Depends on `config` (`GITHUB_REPO`/`GITHUB_TOKEN`/`BOT_UPDATES_CHANNEL_ID`), `embeds`.
- **`restart.py`**: `check_palworld_service`, `restart_palworld`, `auto_restart_sequence`,
  `_bot_restart_in_progress` flag, `_last_auto_restart`/`_auto_restart_task` state,
  `_log_auto_restart_failure`. Depends on `config`, `rest_client`, `bot`, `embeds`.
- **`cause_detection.py`**: `UNATTENDED_UPGRADES_LOG`, `UPGRADE_LOG_RE`, `_read_last_lines`,
  `detect_unattended_upgrades`, `detect_ini_settings_change`, `CAUSE_DETECTORS`,
  `detect_unplanned_restart_cause`, plus the settings-snapshot cache itself:
  `PALWORLD_SETTINGS_CACHE_PATH`, `last_palworld_settings` state,
  `load_last_palworld_settings`/`save_last_palworld_settings`, and
  `check_palworld_settings_change` (moved here from the log-tailer section of the current file,
  since it reads/writes the same cache `detect_ini_settings_change` already owns). Depends on
  `config`, `palworld_settings`, `embeds` (for the settings-changed alert).
- **`log_tailer.py`**: `JOIN_RE`/`LEAVE_RE`/`TS_RE`/`SHUTDOWN_RE`/`VERSION_RE`, `log_tailer()`.
  Calls `cause_detection.check_palworld_settings_change()` (VERSION_RE branch) and
  `cause_detection.save_last_palworld_settings(...)` (shutdown branch, when a settings change is
  the detected cause). Depends on `config`, `embeds`, `player_history`,
  `stats` (`update_stats_message`), `restart` (`_bot_restart_in_progress` flag),
  `cause_detection`.
- **`stats.py`**: `stats_message_id` state, `_stats_lock`, `update_stats_message`,
  `stats_ticker`. Depends on `config`, `bot`, `rest_client`, `player_history`, `embeds`, `ram`,
  `restart` (auto-restart trigger).
- **`commands.py`**: the seven `@bot.tree.command` functions and `on_app_command_error`.
  Depends on `bot`, `rest_client`, `player_history`, `embeds`, `restart`.
- **`main.py`**: `on_message`, `on_ready`, `main()` coroutine, `if __name__ == "__main__"`.
  Imports `commands` (for its registration side effect), `stats`, `releases`, `log_tailer`,
  `restart`, `player_history`, and `cause_detection` (for `load_last_palworld_settings` at
  startup), wires up the background tasks, and runs the bot.

### Dependency direction

```
config, bot  (leaves)
  → rest_client, ram, palworld_settings, embeds
      → player_history, releases, restart, cause_detection
          → stats, log_tailer
              → commands
                  → main.py
```

No cycles: each module only imports modules to its left/above.

## Migration approach

Mechanical move, verified by diff-reading rather than behavior testing (no test suite exists
yet, per `CLAUDE.md`):

1. Create `swee/` package with the modules above, moving code verbatim (same function bodies,
   same names) and adding the necessary imports between modules.
2. Replace `main.py`'s content with the thin composition root described above.
3. Update `README.md`'s reference to `CAUSE_DETECTORS` living in `main.py` to point at
   `swee/cause_detection.py`.
4. Sanity-check: `python -c "import main"` (or equivalent) succeeds with no `ImportError`, and a
   manual read-through confirms every top-level name from the original `main.py` has exactly one
   new home.

## Non-goals / risks accepted

- No behavior change, no bug fixes, no API changes — anything found along the way (e.g. the
  shared mutable globals) is logged as a follow-up idea, not fixed here.
- Not introducing a `tests/` suite as part of this change — out of scope, and `CLAUDE.md` already
  notes there isn't one yet.
- Slightly more files to navigate for small future changes that used to touch one file — accepted
  trade-off for keeping each module small enough to hold in context, per the project's own
  600-line split trigger already being well past (980 lines).
