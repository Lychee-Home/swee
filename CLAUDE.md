# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

`swee` is a single-file Discord bot (`main.py`) that bridges a Palworld dedicated server with a
Discord guild: it relays chat/join/leave activity from the server's journalctl logs, keeps a
live-updating stats embed pinned in a channel, and exposes slash commands for status checks and
admin actions (save, kick, ban, broadcast, restart) via Palworld's REST API. See `README.md` for
architecture and setup details.

- Python 3.13 (see `.idea/misc.xml` for the configured interpreter, named `swee`)
- Dependencies are pinned in `requirements.txt` (discord.py, httpx, python-dotenv, plus transitive
  requests/urllib3/certifi/idna/charset-normalizer pins); install with `pip install -r requirements.txt`
  into the `.venv` at the repo root
- Configuration is via environment variables loaded from a `.env` file (see `.env.example` for the
  full list — bot token, guild/channel/role IDs, Palworld REST credentials)
- There are no automated tests or test runner configured yet
- The bot assumes it runs on the same Linux host as the Palworld server (it shells out to
  `journalctl`/`systemctl` and reads `/proc/meminfo` directly) — it will not run as-is on Windows

## Working in this repo

- All bot logic currently lives in `main.py`; there's no package structure yet. Ask the user before
  introducing one (e.g. splitting into modules) rather than assuming it's wanted.
- When adding dependencies, add them to `requirements.txt`.
- When adding a test suite or lint tooling, update this file with the actual run/build/lint/test
  commands.
- Non-trivial features get a design spec and implementation plan committed under
  `docs/superpowers/specs/` and `docs/superpowers/plans/` (see `superpowers:brainstorming` and
  `superpowers:writing-plans`), named `YYYY-MM-DD-<topic>-design.md` / `YYYY-MM-DD-<topic>.md`.
  Keep them — they capture design rationale (why, not just what) that isn't recoverable from a
  diff or commit message alone.
