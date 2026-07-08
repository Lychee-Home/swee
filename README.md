# swee

A Discord bot that bridges a Palworld dedicated server with a Discord guild: relays chat/join/leave
activity, keeps a live-updating stats embed, and exposes slash commands for status checks and admin
actions (save, kick, ban, broadcast, restart).

## How it works

- **Palworld REST API** (`REST_HOST`/`REST_PORT`) — used for server info, player list, metrics,
  announcements, saves, kicks, and bans.
- **`journalctl -u palworld -f`** — tailed for chat/join/leave/shutdown/version log lines, which are
  posted to `ACTIVITY_CHANNEL_ID` as embeds.
- **Stats embed** — a single pinned message in `STATS_CHANNEL_ID`, edited in place every minute (and
  on join/leave) with player count, FPS, uptime, version, and host system RAM usage (read from
  `/proc/meminfo`, so this must run on Linux, on the same box as the game server).
- **RAM auto-restart** (optional) — if `RAM_RESTART_THRESHOLD_PCT` is set, the stats ticker
  restarts the `palworld` service whenever host RAM usage crosses that percentage. Players get
  a Discord activity-channel warning and an in-game announcement `RAM_RESTART_WARNING_SEC`
  (default 60s) before the restart fires, and a `RAM_RESTART_COOLDOWN_MIN` (default 15min)
  cooldown prevents repeat triggers while the server is still booting back up.
- **Relay channel** — messages posted in `RELAY_CHANNEL_ID` are forwarded to the game via the REST
  announce endpoint.

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

## Requirements

- Python 3.13
- Dependencies pinned in `requirements.txt` (discord.py>=2.7.1, httpx, python-dotenv, plus
  transitive pins). Note: discord.py 2.7.1's published support range tops out at Python 3.12, so
  watch for install/compatibility issues on 3.13.
- A running Palworld dedicated server with the REST API enabled
- A Discord bot application with `message_content` intent enabled in the Developer Portal
