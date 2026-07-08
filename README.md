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

## Running

```
python main.py
```

Slash commands are synced to `GUILD_ID` on startup. Admin-only commands (`save`, `kick`, `ban`,
`broadcast`, `restart`) require `ADMIN_ROLE_ID`. `restart` and the RAM reader shell out to
`systemctl`/`/proc`, so the bot is expected to run on the same Linux host as the Palworld service.

## Requirements

- Python 3.13
- A running Palworld dedicated server with the REST API enabled
- A Discord bot application with `message_content` intent enabled in the Developer Portal
