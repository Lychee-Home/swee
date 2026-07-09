# Online/offline player tables in the stats embed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `Players: n/max` field in the pinned stats embed (and `/status`) with an
`Online` table (name/level/ping) and an `Offline` table (name/last-seen), backed by a small
JSON file that survives bot restarts.

**Architecture:** Player identity is resolved from Palworld's REST `userId` field (captured at
join time from `rest.players()`, since the journalctl join/leave log lines only carry a display
name). A module-level `player_history` dict (`userId -> {name, last_seen}`) is updated on join,
leave, and every 1-minute ticker tick, and persisted to `player_history.json` after each change.
Rendering logic is pure functions so they can be exercised without discord/httpx.

**Tech Stack:** Python 3.13, discord.py, httpx (existing — no new dependencies).

## Global Constraints

- No automated test runner exists in this repo (per `CLAUDE.md`) — verification is manual,
  either via standalone `python -c` snippets for pure logic or live testing against the real
  server for anything touching discord.py/httpx.
- All bot logic lives in `main.py` — no new modules (per `CLAUDE.md`, ask before splitting).
- New env vars get defaults via `os.environ.get(...)`, following the existing pattern for
  `RAM_RESTART_COOLDOWN_MIN` etc. (main.py:37-38).
- Spec: `docs/superpowers/specs/2026-07-08-player-history-embed-design.md`.

---

### Task 1: Persistence layer and pure rendering/formatting functions

**Files:**
- Modify: `main.py` (new code block after the module state at main.py:125-130; config near
  main.py:32-38; `.gitignore`; `.env.example`)

**Interfaces:**
- Produces: `PLAYER_HISTORY_PATH: str`, `OFFLINE_PLAYERS_LIMIT: int`, `player_history: dict`,
  `online_players: dict`, `load_player_history() -> None`, `save_player_history() -> None`,
  `offline_entries_from_history(history: dict, online_ids: set) -> list[tuple[str, int]]`,
  `format_online_field(players: list[dict]) -> str`, `format_offline_field(entries: list[tuple[str, int]], limit: int) -> str`.

- [ ] **Step 1: Add config and module state**

In `main.py`, after `RAM_RESTART_WARNING_SEC` (main.py:38), add:

```python
OFFLINE_PLAYERS_LIMIT = int(os.environ.get("OFFLINE_PLAYERS_LIMIT", "10"))
```

After the existing module state block (main.py:125-130, the `stats_message_id` /
`_stats_lock` / etc. group), add:

```python
PLAYER_HISTORY_PATH = "player_history.json"
player_history = {}   # userId -> {"name": str, "last_seen": ISO8601 str}
online_players = {}   # display name -> userId, refreshed on join/leave/tick
```

- [ ] **Step 2: Add persistence functions**

Directly below the state added in Step 1:

```python
def load_player_history():
    global player_history
    try:
        with open(PLAYER_HISTORY_PATH) as f:
            player_history = json.load(f)
    except FileNotFoundError:
        player_history = {}
    except json.JSONDecodeError:
        log.warning("player_history.json is corrupt, starting with empty history")
        player_history = {}


def save_player_history():
    with open(PLAYER_HISTORY_PATH, "w") as f:
        json.dump(player_history, f, indent=2)
```

- [ ] **Step 3: Add the pure offline-entries builder and verify it standalone**

Below `save_player_history()`:

```python
def offline_entries_from_history(history, online_ids):
    entries = []
    for uid, rec in history.items():
        if uid in online_ids:
            continue
        dt = datetime.fromisoformat(rec["last_seen"])
        entries.append((rec["name"], int(dt.timestamp())))
    entries.sort(key=lambda e: e[1], reverse=True)
    return entries
```

Verify with a standalone snippet (doesn't touch discord/httpx, safe to run directly):

```bash
python -c "
from datetime import datetime
history = {
    'a': {'name': 'Alice', 'last_seen': '2026-07-08T10:00:00+00:00'},
    'b': {'name': 'Bob',   'last_seen': '2026-07-08T12:00:00+00:00'},
    'c': {'name': 'Carol', 'last_seen': '2026-07-08T11:00:00+00:00'},
}
def offline_entries_from_history(history, online_ids):
    entries = []
    for uid, rec in history.items():
        if uid in online_ids:
            continue
        dt = datetime.fromisoformat(rec['last_seen'])
        entries.append((rec['name'], int(dt.timestamp())))
    entries.sort(key=lambda e: e[1], reverse=True)
    return entries
result = offline_entries_from_history(history, online_ids={'b'})
names = [name for name, _ in result]
assert names == ['Carol', 'Alice'], names
print('OK', result)
"
```

Expected: `OK [('Carol', 1783684800), ('Alice', 1783681200)]` (exact timestamps depend on the
literal ISO strings above, but the order and names must match).

- [ ] **Step 4: Add the pure formatting functions and verify them standalone**

Below `offline_entries_from_history`:

```python
def format_online_field(players):
    if not players:
        return "No one online."
    return "\n".join(f"**{p['name']}** — Lv.{p['level']} ({round(p['ping'])}ms)" for p in players)


def format_offline_field(entries, limit):
    if not entries:
        return "None yet."
    lines = [f"**{name}** — <t:{ts}:R>" for name, ts in entries[:limit]]
    if len(entries) > limit:
        lines.append(f"…and {len(entries) - limit} more")
    return "\n".join(lines)
```

Run:
```bash
python -c "
def format_online_field(players):
    if not players:
        return 'No one online.'
    return chr(10).join(f\"**{p['name']}** — Lv.{p['level']} ({round(p['ping'])}ms)\" for p in players)
def format_offline_field(entries, limit):
    if not entries:
        return 'None yet.'
    lines = [f'**{name}** — <t:{ts}:R>' for name, ts in entries[:limit]]
    if len(entries) > limit:
        lines.append(f'…and {len(entries) - limit} more')
    return chr(10).join(lines)

assert format_online_field([]) == 'No one online.'
assert format_online_field([{'name': 'Kippei', 'level': 39, 'ping': 64.2857}]) == '**Kippei** — Lv.39 (64ms)'
assert format_offline_field([], 10) == 'None yet.'
entries = [(f'P{i}', 1000 - i) for i in range(12)]
out = format_offline_field(entries, 10)
assert out.count(chr(10)) == 10, out  # 10 name lines + 1 overflow line = 11 lines = 10 newlines
assert out.endswith('…and 2 more'), out
print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 5: Add `.gitignore` entry and `.env.example` entry**

Append to `.gitignore`:
```
player_history.json
```

In `.env.example`, after the RAM auto-restart block (currently ends at line 28), add:

```
# --- Player history (optional) ---
# Max offline players shown in the stats embed, most-recently-seen first.
# OFFLINE_PLAYERS_LIMIT=10
```

- [ ] **Step 6: Commit**

```bash
git add main.py .gitignore .env.example
git commit -m "Add player history persistence and pure rendering helpers"
```

---

### Task 2: Resolve join/leave log lines to stable player IDs

**Files:**
- Modify: `main.py:315-320` (the `JOIN_RE`/`LEAVE_RE` branches inside `log_tailer()`)

**Interfaces:**
- Consumes: `player_history`, `online_players`, `save_player_history()` (Task 1); `rest.players()`
  (main.py:68, existing — returns `{"players": [{"name", "accountName", "playerId", "userId",
  "ip", "ping", "location_x", "location_y", "level"}, ...]}`).
- Produces: `record_join(name: str, dt: datetime) -> None`, `record_leave(name: str, dt: datetime) -> None`.

- [ ] **Step 1: Add `record_join` and `record_leave`**

Add these functions right after `save_player_history()` (below the functions added in Task 1,
Steps 2-4 — exact placement doesn't matter as long as they're defined before `log_tailer()`
uses them):

```python
async def record_join(name, dt):
    try:
        data = await rest.players()
    except Exception:
        log.exception("player history: failed to fetch players on join for %s", name)
        return
    for p in data.get("players", []):
        if p["name"] == name:
            uid = p["userId"]
            online_players[name] = uid
            player_history[uid] = {"name": name, "last_seen": dt.isoformat()}
            save_player_history()
            return


async def record_leave(name, dt):
    uid = online_players.pop(name, None)
    if uid is None:
        uid = next((k for k, v in player_history.items() if v["name"] == name), None)
    if uid is None:
        uid = f"name:{name}"
        log.warning("player history: no stable ID found for %s on leave, using fallback key", name)
    player_history[uid] = {"name": name, "last_seen": dt.isoformat()}
    save_player_history()
```

- [ ] **Step 2: Wire into `log_tailer()`**

Current (main.py:315-320):
```python
                    if m := JOIN_RE.search(rest_msg):
                        await broadcast_embed(f"{m.group(1)} joined the server", None, COLOR_JOIN, dt)
                        await update_stats_message()
                    elif m := LEAVE_RE.search(rest_msg):
                        await broadcast_embed(f"{m.group(1)} left the server", None, COLOR_LEAVE, dt)
                        await update_stats_message()
```

New:
```python
                    if m := JOIN_RE.search(rest_msg):
                        await broadcast_embed(f"{m.group(1)} joined the server", None, COLOR_JOIN, dt)
                        await record_join(m.group(1), dt)
                        await update_stats_message()
                    elif m := LEAVE_RE.search(rest_msg):
                        await broadcast_embed(f"{m.group(1)} left the server", None, COLOR_LEAVE, dt)
                        await record_leave(m.group(1), dt)
                        await update_stats_message()
```

- [ ] **Step 3: Verify with `python -m py_compile`**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0 (syntax/import sanity check — full behavior is verified live
in Task 5, since this logic depends on `rest.players()` and real log lines).

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "Resolve join/leave log lines to stable player IDs for history tracking"
```

---

### Task 3: Refresh online players and history on every ticker tick

**Files:**
- Modify: `main.py:184-217` (`update_stats_message()`)

**Interfaces:**
- Consumes: `online_players`, `player_history`, `save_player_history()` (Task 1);
  `rest.players()` (existing).
- Produces: `refresh_online_players(players_list: list[dict]) -> None`.

- [ ] **Step 1: Add `refresh_online_players`**

Add below `record_leave` (Task 2):

```python
def refresh_online_players(players_list):
    online_players.clear()
    now_iso = datetime.now(timezone.utc).astimezone(PACIFIC).isoformat()
    for p in players_list:
        uid = p["userId"]
        online_players[p["name"]] = uid
        player_history[uid] = {"name": p["name"], "last_seen": now_iso}
    save_player_history()
```

- [ ] **Step 2: Fetch players and refresh state in `update_stats_message()`**

Current (main.py:192-195):
```python
    async with _stats_lock:
        try:
            info, metrics = await rest.info(), await rest.metrics()
            embed = build_stats_embed(info, metrics)
```

New:
```python
    async with _stats_lock:
        try:
            info, metrics = await rest.info(), await rest.metrics()
            try:
                players_list = (await rest.players()).get("players", [])
                refresh_online_players(players_list)
            except Exception:
                log.exception("player history: failed to refresh online players")
                players_list = []
            offline_entries = offline_entries_from_history(player_history, set(online_players.values()))
            embed = build_stats_embed(info, metrics, players_list, offline_entries)
```

(`build_stats_embed`'s new signature is added in Task 4 — this task's own verification is
deferred to Task 4 Step 4, since the two changes are only testable together: this step alone
would leave `build_stats_embed` called with a mismatched signature.)

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "Refresh online player state from REST on every stats tick"
```

---

### Task 4: Render Online/Offline fields in the embed

**Files:**
- Modify: `main.py:164-181` (`add_status_fields`, `build_stats_embed`)
- Modify: `main.py:345-351` (`/status` command)

**Interfaces:**
- Consumes: `format_online_field`, `format_offline_field`, `OFFLINE_PLAYERS_LIMIT` (Task 1);
  `offline_entries_from_history` (Task 1); `refresh_online_players`, `player_history`,
  `online_players` (Tasks 1-3).
- Produces: `add_status_fields(embed, info, metrics, players, offline_entries)`,
  `build_stats_embed(info, metrics, players, offline_entries)` — new signatures, replacing the
  old 2-arg / 2-arg versions everywhere they're called.

- [ ] **Step 1: Update `add_status_fields` and `build_stats_embed`**

Current (main.py:164-181):
```python
def add_status_fields(embed, info, metrics):
    embed.add_field(name="Players", value=f"{metrics['currentplayernum']}/{metrics['maxplayernum']}")
    embed.add_field(name="FPS", value=metrics["serverfps"])
    embed.add_field(name="Uptime", value=f"{metrics['uptime'] // 3600}h")
    embed.add_field(name="Version", value=info["version"])
    return embed


def build_stats_embed(info, metrics):
    embed = discord.Embed(title=info["servername"], color=COLOR_READY)
    add_status_fields(embed, info, metrics)
    try:
        embed.add_field(name="System RAM", value=get_ram_usage())
    except Exception:
        log.exception("RAM read failed")
    embed.timestamp = datetime.now(timezone.utc)
    embed.set_footer(text="Last updated")
    return embed
```

New:
```python
def add_status_fields(embed, info, metrics, players, offline_entries):
    embed.add_field(name="Online", value=format_online_field(players), inline=False)
    embed.add_field(name="Offline", value=format_offline_field(offline_entries, OFFLINE_PLAYERS_LIMIT), inline=False)
    embed.add_field(name="FPS", value=metrics["serverfps"])
    embed.add_field(name="Uptime", value=f"{metrics['uptime'] // 3600}h")
    embed.add_field(name="Version", value=info["version"])
    return embed


def build_stats_embed(info, metrics, players, offline_entries):
    embed = discord.Embed(title=info["servername"], color=COLOR_READY)
    add_status_fields(embed, info, metrics, players, offline_entries)
    try:
        embed.add_field(name="System RAM", value=get_ram_usage())
    except Exception:
        log.exception("RAM read failed")
    embed.timestamp = datetime.now(timezone.utc)
    embed.set_footer(text="Last updated")
    return embed
```

- [ ] **Step 2: Update `/status` command**

Current (main.py:345-351):
```python
@bot.tree.command(description="Show server status")
@in_commands_channel()
async def status(interaction: discord.Interaction):
    info, metrics = await rest.info(), await rest.metrics()
    embed = discord.Embed(title=info["servername"], color=COLOR_CHAT)
    add_status_fields(embed, info, metrics)
    await interaction.response.send_message(embed=embed, ephemeral=True)
```

New:
```python
@bot.tree.command(description="Show server status")
@in_commands_channel()
async def status(interaction: discord.Interaction):
    info, metrics = await rest.info(), await rest.metrics()
    try:
        players_list = (await rest.players()).get("players", [])
    except Exception:
        log.exception("player history: failed to fetch players for /status")
        players_list = []
    offline_entries = offline_entries_from_history(player_history, set(online_players.values()))
    embed = discord.Embed(title=info["servername"], color=COLOR_CHAT)
    add_status_fields(embed, info, metrics, players_list, offline_entries)
    await interaction.response.send_message(embed=embed, ephemeral=True)
```

- [ ] **Step 3: Load history at startup**

Current (main.py:494-499):
```python
async def main():
    discord.utils.setup_logging()
    if not check_palworld_service():
        raise SystemExit(1)
    async with bot:
        await bot.start(BOT_TOKEN)
```

New:
```python
async def main():
    discord.utils.setup_logging()
    if not check_palworld_service():
        raise SystemExit(1)
    load_player_history()
    async with bot:
        await bot.start(BOT_TOKEN)
```

- [ ] **Step 4: Verify with `python -m py_compile`**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0. This confirms Tasks 3 and 4 are wired together consistently
(matching call signatures for `build_stats_embed`/`add_status_fields`) — full runtime behavior
is verified live in Task 5.

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "Render Online/Offline player tables in the stats embed and /status"
```

---

### Task 5: End-to-end verification against the real server

**Files:** none (manual verification only — no code changes)

- [ ] **Step 1: Deploy and restart the bot**

Follow the existing deploy process (see `deploy.sh` / systemd unit from the prior
idempotent-deploy work) to run the updated `main.py` on the Palworld host.

- [ ] **Step 2: Confirm the stats embed renders both fields**

Check the pinned message in `STATS_CHANNEL_ID`. Expected: `Online` field shows `No one
online.` or the current player list in `**name** — Lv.X (Yms)` format; `Offline` field shows
`None yet.` on a fresh `player_history.json`, or prior entries if one already exists.

- [ ] **Step 3: Confirm join updates the embed and history file**

Have a player join the server. Expected: within the next ticker tick (≤1 min) or immediately
via the join-triggered `update_stats_message()` call, the `Online` field includes them.
On the host, run `cat player_history.json` — expected: an entry keyed by their `steam_...`
`userId` with their name and a recent `last_seen`.

- [ ] **Step 4: Confirm leave updates the embed**

Have the same player leave. Expected: `Online` field goes back to `No one online.` (or drops
them), and `Offline` field now shows `**name** — <t:...:R>` rendering as "a few seconds ago" in
Discord (verify the Discord client renders the relative-time tag, not a raw `<t:...>` string).

- [ ] **Step 5: Confirm `/status` matches**

Run `/status` in the configured commands channel. Expected: same Online/Offline content as the
pinned embed.

- [ ] **Step 6: Confirm persistence across a restart**

Restart the bot process. Expected: `Offline` field still shows the player from Step 4 (history
survived the restart) — confirms `load_player_history()` at startup works.

- [ ] **Step 7: Confirm the offline cap**

If there are more than `OFFLINE_PLAYERS_LIMIT` (default 10) distinct offline entries in
`player_history.json` (or temporarily lower `OFFLINE_PLAYERS_LIMIT` in `.env` to 2-3 to test
with fewer real players), expected: only the N most recent show, followed by a `…and N more`
line.

No commit for this task — it's verification of the already-committed Tasks 1-4. If any step
fails, fix the relevant task's code and amend forward with a new commit (don't silently patch
without a task reference).
