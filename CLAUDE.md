# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

`swee` is a Discord bot that bridges a Palworld dedicated server with a Discord server: it relays
join/leave activity from the server's journalctl logs, keeps a live-updating stats embed
pinned in a channel, and exposes slash commands for status checks and admin actions (save, kick,
ban, broadcast, restart, config view/edit) via Palworld's REST API and its `PalWorldSettings.ini`
file. `main.py` is the entrypoint; bot logic lives in the `swee/` package (`bot.py`, `commands.py`,
`config_commands.py`, `log_tailer.py`, `restart.py`, `palworld_settings.py`, etc. — one module per
concern). See `README.md` for architecture and setup details.

- Python 3.14 (see `.idea/misc.xml` for the configured interpreter, named `swee`)
- Dependencies are pinned in `requirements.txt` (discord.py, httpx, python-dotenv, plus transitive
  requests/urllib3/certifi/idna/charset-normalizer pins); install with `pip install -r requirements.txt`
  into the `.venv` at the repo root
- Configuration is via environment variables loaded from a `.env` file (see `.env.example` for the
  full list — bot token, guild/channel/role IDs, Palworld REST credentials)
- `tests/test_palworld_settings.py` covers the pure ini-parsing/writing/validation functions in
  `swee/palworld_settings.py`; run with `python -m unittest discover tests -v`. No coverage of the
  Discord command layer itself (no test harness for that yet) — verify those manually.
- The bot assumes it runs on the same Linux host as the Palworld server (it shells out to
  `journalctl`/`systemctl` and reads `/proc/meminfo` directly) — it will not run as-is on Windows

## Working in this repo

- Bot logic lives in the `swee/` package, one module per concern (commands, log tailing, restart,
  embeds, ini parsing, etc.); `main.py` just wires them together at startup. Follow this pattern
  for new functionality — new commands/features generally warrant their own module (e.g.
  `swee/config_commands.py`) rather than growing an existing one indefinitely.
- When adding dependencies, add them to `requirements.txt`.
- When adding a test suite or lint tooling, update this file with the actual run/build/lint/test
  commands.
- Never push directly to `main` — pushes to `main` feed a standing release-please Release PR,
  and merging *that* PR is what deploys the live bot (see `docs/deployment.md`), so every change
  goes through a feature branch and a PR, even small ones. Create a branch, commit there, push
  it, and open a PR instead of pushing to `main` directly.
- Non-trivial features get a design spec and implementation plan committed under
  `docs/superpowers/specs/` and `docs/superpowers/plans/` (see `superpowers:brainstorming` and
  `superpowers:writing-plans`), named `YYYY-MM-DD-<topic>-design.md` / `YYYY-MM-DD-<topic>.md`.
  Keep them — they capture design rationale (why, not just what) that isn't recoverable from a
  diff or commit message alone.
