# swee

A Discord bot that bridges a Palworld dedicated server with a Discord guild: relays chat/join/leave
activity, keeps a live-updating stats embed, and exposes slash commands for status checks and admin
actions (save, kick, ban, broadcast, restart).

## How it works

- **Palworld REST API** (`REST_HOST`/`REST_PORT`) — used for server info, player list, metrics,
  announcements, saves, kicks, and bans.
- **`journalctl -u $PALWORLD_SERVICE_NAME -f`** (`palworld` by default) — tailed for chat/join/leave/shutdown/version log lines. Join/leave
  and chat relay are posted to `ACTIVITY_CHANNEL_ID` as embeds; server shutdown and server-online
  messages go to `ALERTS_CHANNEL_ID` instead.
- **Unplanned-restart notification** — a shutdown triggered by `/restart` or the RAM auto-restart
  posts the plain "Server shutting down" message as above. Any other shutdown (host-level restart,
  crash, a package upgrade cycling the service, etc.) instead posts "Server restarted unexpectedly"
  with a best-effort "Likely cause" field. The cause is filled in by a small extensible list of
  detectors (`CAUSE_DETECTORS` in `main.py`) — currently one, which recognizes an
  `unattended-upgrades` package install immediately preceding the restart (the `needrestart`
  pattern). No match falls back to "Unknown — an admin will need to check the server logs."
- **Stats embed** — a single pinned message in `STATS_CHANNEL_ID`, edited in place every minute (and
  on join/leave) with player count, FPS, uptime, version, and host system RAM usage (read from
  `/proc/meminfo`, so this must run on Linux, on the same box as the game server).
- **RAM auto-restart** (optional) — if `RAM_RESTART_THRESHOLD_PCT` is set, the stats ticker
  restarts the Palworld service (`PALWORLD_SERVICE_NAME`, `palworld` by default) whenever host RAM usage crosses that percentage. Players get
  an `ALERTS_CHANNEL_ID` warning and an in-game announcement `RAM_RESTART_WARNING_SEC`
  (default 60s) before the restart fires, and a `RAM_RESTART_COOLDOWN_MIN` (default 15min)
  cooldown prevents repeat triggers while the server is still booting back up. The restart result
  is also posted to `ALERTS_CHANNEL_ID`.
- **Relay channel** — messages posted in `RELAY_CHANNEL_ID` are forwarded to the game via the REST
  announce endpoint.
- **Release announcements** — every 5 minutes the bot polls the GitHub Releases API
  (`GITHUB_REPO`) for the latest release; when a new one appears, it humanizes the
  auto-generated release notes (Conventional Commit prefixes and PR references stripped,
  grouped into "New"/"Fixes") and posts an embed to `BOT_UPDATES_CHANNEL_ID`. The last
  announced tag is cached in `last_release.json`; deleting that file makes the bot
  re-seed from the current latest release on next startup without re-announcing it.
- **Settings-change alert** — every time the server comes back online after a restart (planned
  or unplanned), the bot reads `PALWORLD_SETTINGS_INI_PATH` and
  compares it to the last-seen snapshot (`last_palworld_settings.json`). Any added, removed, or
  changed setting posts an embed to `ALERTS_CHANNEL_ID` listing each change as `Old → New`;
  `AdminPassword`/`ServerPassword` changes show as `(changed)` rather than the real values. The
  first check after a fresh deploy seeds the baseline silently instead of alerting.

## Setup

```
python -m venv .venv
.venv/Scripts/activate   # or `source .venv/bin/activate` on Linux
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` with your bot token, guild/channel/role IDs, and Palworld REST credentials, then
restrict its permissions (`chmod 600 .env` on Linux — it holds secrets).
`RAM_RESTART_THRESHOLD_PCT` and its companions are optional — leave them unset to keep
auto-restart disabled.

You can edit and install dependencies on any OS, but the bot itself must **run** on Linux (see below).

## Running

```
python main.py
```

Slash commands are synced to `GUILD_ID` on startup. Admin-only commands (`save`, `kick`, `ban`,
`broadcast`, `restart`) require `ADMIN_ROLE_ID`. `restart` and the RAM reader shell out to
`systemctl`/`/proc`, and `log_tailer` shells out to `journalctl`, so the bot must run on the same
Linux host as the Palworld service — it will not run as-is on Windows.

The systemd unit managing the Palworld service defaults to `palworld` — set `PALWORLD_SERVICE_NAME`
in `.env` if yours is named differently (e.g. when running multiple Palworld servers on one host).
Additionally, the user running the bot must have passwordless `sudo` configured for the
`systemctl restart <PALWORLD_SERVICE_NAME>` command (e.g. via a `NOPASSWD` sudoers entry) —
otherwise the bot exits immediately at startup with a clear error in the log.

## Deployment

For a Linux host you set up once and leave running, `deploy/setup.sh` automates the steps above
plus the systemd wiring: it creates the venv, installs dependencies, copies `.env.example` to
`.env` (without overwriting an existing one), checks that the configured Palworld service (from
`PALWORLD_SERVICE_NAME` in `.env`, `palworld` by default) exists, installs a passwordless-sudo rule
scoped to restarting it, and installs/enables a `swee.service` unit (rendered from
`deploy/swee.service`). It's safe to re-run — it skips any step
that's already in the desired state.

```
git clone <repo> && cd swee
./deploy/setup.sh
# fill in .env with your secrets
sudo systemctl start swee
```

Manage the running bot with `systemctl {status,stop,restart} swee` and `journalctl -u swee -f`.

### Continuous deployment

Pushes to `main` auto-deploy via `.github/workflows/deploy.yml`, which runs on a self-hosted
GitHub Actions runner installed on the same host as the bot (see [GitHub's
docs](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners)
for installing the runner itself). On each push the runner `cd`s into the deployed repo
(`$SWEE_DIR`, defaulting to `~/swee` — override with a repo variable of the same name if cloned
elsewhere), does a `git pull --ff-only`, reinstalls dependencies, and restarts `swee.service`. No
inbound access to the host is required since the runner polls GitHub outbound; `deploy/setup.sh`
installs the passwordless-sudo rule (`systemctl restart swee`) the workflow needs to restart the
service non-interactively.

### Versioning

Releases are tagged automatically. Every PR title must follow [Conventional
Commits](https://www.conventionalcommits.org/) format (`feat: ...`, `fix: ...`, `chore: ...`,
etc. — enforced by a PR check, though not merge-blocking). Squash merge is the only allowed
merge method, so each PR becomes exactly one commit on `main` titled with its PR title.

On push to `main`, `.github/workflows/release.yml` reads that commit's type:
- `feat` bumps MINOR, `fix`/`perf` bump PATCH, and a `!` after the type/scope (or a line in the
  PR description that starts with `BREAKING CHANGE:`) bumps MAJOR — each creates a new
  `vX.Y.Z` tag and GitHub Release with auto-generated notes. The footer must start a line;
  merely mentioning the phrase elsewhere in the description doesn't trigger it.
- Any other type (`docs`, `chore`, `ci`, `style`, `test`, `refactor`, `build`, `revert`) merges
  without a release.

Reserve `!`/`BREAKING CHANGE:` for changes that break an existing deployment on upgrade — e.g. a
new required `.env` var, a removed/renamed slash command, a changed REST config shape.

## Requirements

- Python 3.14
- Dependencies pinned in `requirements.txt` (discord.py>=2.7.1, httpx, python-dotenv, plus
  transitive pins). Watch for install/compatibility issues on new Python releases, since
  dependency wheels sometimes lag behind.
- A running Palworld dedicated server with the REST API enabled
- A Discord bot application with `message_content` intent enabled in the Developer Portal
