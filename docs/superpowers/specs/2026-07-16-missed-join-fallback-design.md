# Fallback join notification for missed "joined the server" log lines

## Problem

Discord join notifications in `swee/log_tailer.py` fire only on a literal `"[LOG] X joined the
server"` line. Palworld's dedicated server does not reliably emit that line for every connection —
`"X connected the server"` sometimes appears with no matching `"joined"` line ever following it,
even for sessions where the player is clearly in-game and chatting for minutes.

A 14-day journalctl audit of `palworld-palchuds` on `lychee` found 17 such cases:

- 13 were short (17–40s) `connected → left` pairs with no `joined` in between — most likely failed
  or aborted connection attempts (client bounces before fully loading in). These should stay
  silent, same as today.
- 4 were `connected → connected` pairs with no `joined` or `left` in between — a retried connection
  attempt.
- 2 were genuine multi-minute sessions (2m27s, 3m12s) with real chat activity that got **zero**
  join notification, only a leave — producing the confusing "X left the server" with no preceding
  join that prompted this investigation.

## Design

### State: pending-connect timers

Add to `swee/log_tailer.py`:

```python
CONNECT_RE = re.compile(r'\[LOG\]\s*(.+?) [\d.]+ connected the server')

pending_connects = {}  # display name -> asyncio.Task
```

`pending_connects` tracks, per player name, a scheduled fallback-join task started by a `connected`
line. It is in-memory only (module-level dict), matching the existing pattern of `online_players` /
`session_started` in `player_history.py` — safe without a lock because mutation never crosses an
`await` boundary except inside the scheduled task itself.

### Fallback task

```python
async def _fallback_join(name, dt):
    await asyncio.sleep(30)
    pending_connects.pop(name, None)
    await broadcast_embed(f"{name} joined the server", None, COLOR_JOIN, dt)
    await record_join(name, dt)
    await update_stats_message()
```

30 seconds is the fallback window: none of the 13 observed bounce-cases exceeded 40s from `connected`
to `left`, so those are caught and cancelled well before the timer would fire; both real missed-join
sessions (2m27s, 3m12s) run long past 30s, so the fallback fires for them with room to spare.

### Wiring into the tailer loop

In the main `async for line in proc.stdout` loop, alongside the existing `JOIN_RE` / `LEAVE_RE`
branches:

- **On `CONNECT_RE` match:** cancel any existing pending task for that name (handles the
  `connected → connected` case by restarting the 30s window from the newest attempt), then
  schedule a new one: `pending_connects[name] = asyncio.create_task(_fallback_join(name, dt))`.
- **On `JOIN_RE` match:** before the existing notification logic, cancel and pop any pending task
  for that name — the real `joined` line arrived in time, so no fallback should fire.
- **On `LEAVE_RE` match:** before the existing notification logic, cancel and pop any pending task
  for that name — a connect that ended in a leave with no `joined` in between is treated as a
  bounced/failed connection and stays silent, same as today.

Regex order in the loop: `CONNECT_RE` must be checked before `JOIN_RE`/`LEAVE_RE` per line (they're
mutually exclusive matches on different log lines, so simple `if`/`elif` chaining works).

### Reused notification path

The fallback calls the exact same `broadcast_embed` / `record_join` / `update_stats_message` calls
as a normal `joined` event — same title text, same color, same downstream stats/history recording.
No new embed styling or copy. `record_join` already tolerates being invoked at any time; it looks
up the player's `userId` from the REST `/players` endpoint by name, and 30 seconds is enough time
for a genuinely-connected player to appear there.

### Failure handling

If the bot process or the journalctl subprocess restarts (the tailer already retries every 5s on
subprocess exit), any in-flight `pending_connects` tasks are lost along with the rest of the
tailer's in-memory state. This matches the existing behavior of `online_players` / `session_started`
not surviving a restart — not a new gap introduced by this feature.

### Testing

No existing test harness covers the log-tailer/Discord command layer (per `CLAUDE.md`). Verify
manually against the live log stream on `lychee`: trigger a real connect/join, confirm no duplicate
notification; and if reproducible, a connect with a deliberately delayed/suppressed `joined` line.

## Out of scope

- No change to the short-bounce (connect→left within the 30s window) behavior — it stays silent.
- No persistence of `pending_connects` across bot/tailer restarts.
- No configurable timeout — 30s is hardcoded, matching the audit data; not worth a new env var for
  a single internal tuning constant.
