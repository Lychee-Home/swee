# swee

A Discord bot that bridges a Palworld dedicated server with a Discord server: relays join/leave
activity, keeps a live-updating stats embed, and exposes slash commands for status checks and admin
actions (save, kick, ban, broadcast, restart).

## Contents

- [Features](#features)
- [Setup](#setup)
- [Running](#running)
- [Deployment](#deployment)
- [Requirements](#requirements)

## Features

### Activity relay

`journalctl -u $PALWORLD_SERVICE_NAME -f` (`palworld` by default) is tailed for join/leave/
shutdown/version log lines. Join/leave posts to `ACTIVITY_CHANNEL_ID` as embeds; server shutdown
and server-online messages go to `ALERTS_CHANNEL_ID` instead.

A shutdown triggered by `/restart` or the RAM auto-restart is reported as planned ("Server shutting
down"). Any other shutdown (host restart, crash, a package upgrade cycling the service, etc.)
instead posts "Server restarted unexpectedly" with a best-effort "Likely cause" field, filled in by
a small extensible list of detectors (`CAUSE_DETECTORS` in `swee/cause_detection.py` — currently one,
recognizing an `unattended-upgrades` install immediately preceding the restart). No match falls back
to "Unknown — an admin will need to check the server logs."

Messages posted in `RELAY_CHANNEL_ID` are forwarded to the game via the REST announce endpoint.

### Stats embed

A single pinned message in `STATS_CHANNEL_ID`, edited in place every minute (and on join/leave)
with player count, FPS, uptime, version, and host system RAM usage (read from `/proc/meminfo`, so
this must run on Linux, on the same box as the game server). Online and Offline player lists sit
side by side as inline fields, with FPS/Uptime/Day/Version on their own row below. Uptime is shown
as a humanized duration (e.g. "3d 4h", "2w 1d", "1mo 3d") rather than a raw hour count.

### RAM auto-restart (optional)

If `RAM_RESTART_THRESHOLD_PCT` is set, the stats ticker restarts the Palworld service
(`PALWORLD_SERVICE_NAME`) whenever host RAM usage crosses that percentage. Players get an
`ALERTS_CHANNEL_ID` warning and an in-game announcement `RAM_RESTART_WARNING_SEC` (default 60s)
before the restart fires, and a `RAM_RESTART_COOLDOWN_MIN` (default 15min) cooldown prevents repeat
triggers while the server is still booting back up. The restart result is also posted to
`ALERTS_CHANNEL_ID`.

### Release announcements

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

### Settings-change alerts

Every time the server comes back online after a restart (planned or unplanned), the bot reads
`PALWORLD_SETTINGS_INI_PATH` and compares it to the last-seen snapshot
(`last_palworld_settings.json`). Any added, removed, or changed setting posts an embed to
`ALERTS_CHANNEL_ID` listing each change as `Old → New`; `AdminPassword`/`ServerPassword` changes
show as `(changed)` rather than the real values. The first check after a fresh deploy seeds the
baseline silently instead of alerting.

### Config commands

`/config list` (paginated) and `/config get <key>` show current values from
`PALWORLD_SETTINGS_INI_PATH`; `/config set <key> <value>` writes a new value to that file.
`AdminPassword`/`ServerPassword` can't be read or set through the bot. Like any ini edit, a change
made via `/config set` only takes effect after the next `restart`.

### In-game `@swee` assistant (optional)

Players can ask Palworld questions in-game chat by prefixing a message with `@swee`, e.g.
`@swee what does lamball drop?`. The question goes to Claude, which can call a live lookup
against [palworld.wiki.gg](https://palworld.wiki.gg)'s structured pal database (breeding, drops,
work suitability, stats, passive skills) for anything pal-specific, falling back to its own
general Palworld knowledge for broader questions. The answer is broadcast in-game to all players
via the same REST announce endpoint used for the Discord relay, and the question/answer pair is
logged to `ASSISTANT_LOG_CHANNEL_ID` for admin visibility. Each player is limited to one answered
question per `ASK_COOLDOWN_SEC` (default 30s) to limit broadcast spam and API cost. Requires
`ANTHROPIC_API_KEY` — leave it unset to disable the feature entirely.

Each player's questions and answers are remembered as a conversation within their current play
session (up to the last 8 exchanges), so follow-up questions like "what about its passive skills?"
can reference what was already asked — this memory is cleared when the player leaves the server, and
is never shared between players even if they share a display name.

Known limitation: map/resource-location questions (e.g. "where can I find Pure Quartz") aren't
grounded in live data — there's no pal to look up, so these fall back to Claude's general knowledge
and can be vague or wrong. Only pal-specific questions (breeding, drops, work suitability, stats,
passive skills) are backed by a live lookup.

### Pal-catch recap feed (palfeed, optional)

If `PALFEED_SERVICE_URL` is set, the bot polls a companion `palsave-api` service (a separate
repo/deployment that watches the Palworld server's backup rotation and decodes new-pal events)
every 60 seconds via its `GET /events/new-pals` endpoint, and posts notable catches to
`PALFEED_CHANNEL_ID` as an embed. Only catches meeting a notability bar are posted: rare ("Lucky")
pals, awakened pals, or those with a talent score (HP + Attack/Shot + Defense IVs, max 300) of 280+
("Excellent") or 300 ("Perfect") — see `swee/palfeed_notability.py`. Each embed shows the IV total
as a percentage and a Stats field (level, HP/Attack/Defense), is colored by tier, and is timestamped
with the pal's actual `acquired_at` time rather than when the bot noticed it. The last-seen event id
is cached in `palfeed_state.json`; a failed post stops the batch and retries from that event next
tick rather than skipping it. Leave `PALFEED_SERVICE_URL` unset/blank to disable palfeed entirely.

### Server update

`/update` saves the world, stops the Palworld service, runs `steamcmd` against
`PALWORLD_INSTALL_DIR` to update and validate the dedicated server install, then starts the service
back up. The shutdown this causes is treated as planned (no "restarted unexpectedly" alert), and
the existing "Server is online" log-tailer message reports the new version once it's back up. If
`steamcmd` fails, the service is still restarted with the previously-installed files rather than
left down.

## Setup

```
python -m venv .venv
.venv/Scripts/activate   # or `source .venv/bin/activate` on Linux
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` with your bot token, server/channel/role IDs, and Palworld REST credentials, then
restrict its permissions (`chmod 600 .env` on Linux — it holds secrets).
`RAM_RESTART_THRESHOLD_PCT` and its companions are optional — leave them unset to keep
auto-restart disabled. `GITHUB_REPO` is likewise optional — leave it unset to disable release
polling. `GITHUB_TOKEN` is only required if `GITHUB_REPO` is set and private.

You can edit and install dependencies on any OS, but the bot itself must **run** on Linux (see
[Running](#running)).

## Running

```
python main.py
```

Slash commands are synced to `GUILD_ID` on startup. Admin-only commands (`save`, `kick`, `ban`,
`broadcast`, `restart`, `update`, `config list`, `config get`, `config set`) require
`ADMIN_ROLE_ID`. `config set` edits `PALWORLD_SETTINGS_INI_PATH` directly and does not itself
restart the server — run `restart` afterward to apply the change.

`restart` and the RAM reader shell out to `systemctl`/`/proc`, and `log_tailer` shells out to
`journalctl`, so the bot must run on the same Linux host as the Palworld service — **it will not
run as-is on Windows**.

The systemd unit managing the Palworld service defaults to `palworld` — set `PALWORLD_SERVICE_NAME`
in `.env` if yours is named differently (e.g. when running multiple Palworld servers on one host).
The user running the bot must also have passwordless `sudo` configured for the
`systemctl restart <PALWORLD_SERVICE_NAME>` command (e.g. via a `NOPASSWD` sudoers entry) —
otherwise the bot exits immediately at startup with a clear error in the log.

## Deployment

For a Linux host you set up once and leave running, `deploy/setup.sh` automates the steps above
plus the systemd wiring: it creates the venv, installs dependencies, copies `.env.example` to
`.env` (without overwriting an existing one), checks that the configured Palworld service exists,
installs a passwordless-sudo rule scoped to restarting it, and installs/enables a `swee.service`
unit (rendered from `deploy/swee.service`). It's safe to re-run — it skips any step that's already
in the desired state.

```
git clone <repo> && cd swee
./deploy/setup.sh
# fill in .env with your secrets
sudo systemctl start swee
```

Manage the running bot with `systemctl {status,stop,restart} swee` and `journalctl -u swee -f`.

Pushes to `main` update a standing release-please Release PR; merging *that* PR is what deploys
this running instance and tags a release — see [`docs/deployment.md`](docs/deployment.md) for the
full CI/CD and versioning
mechanics.

## Requirements

- Python 3.14
- Dependencies pinned in `requirements.txt` (discord.py>=2.7.1, httpx, python-dotenv, plus
  transitive pins). Watch for install/compatibility issues on new Python releases, since
  dependency wheels sometimes lag behind.
- A running Palworld dedicated server with the REST API enabled
- A Discord bot application with `message_content` intent enabled in the Developer Portal
