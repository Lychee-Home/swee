# Missed Join-Notification Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make swee announce a join even when Palworld's server never emits a `"joined the server"`
log line, by falling back to a 30-second timer keyed off the `"connected the server"` line.

**Architecture:** Add a `CONNECT_RE` regex and a `pending_connects` dict to `swee/log_tailer.py`.
A `connected` line schedules a 30s `_fallback_join` task; a `joined` or `left` line for that same
player cancels it. If the timer fires uncancelled, it runs the same notification path a real
`joined` line would (`broadcast_embed` + `record_join` + `update_stats_message`). No new files, no
new config.

**Tech Stack:** Python 3.14, `asyncio`, existing `swee/` module structure.

## Global Constraints

- Fallback delay is a hardcoded 30 seconds — no new env var (per spec's "Out of scope").
- No automated test harness exists for the log-tailer/Discord layer (see `CLAUDE.md`) — verify
  manually against the live log stream on `lychee`. `tests/` only covers
  `swee/palworld_settings.py`.
- Reuse the exact same notification call a real `joined` line produces — same embed title/color,
  same `record_join` / `update_stats_message` calls. No new embed styling or copy.
- `pending_connects` is in-memory only, module-level, mutated without a lock — safe because (per
  the existing pattern in `swee/player_history.py`) mutation never crosses an `await` boundary
  except inside the scheduled task itself.

---

### Task 1: Add fallback-join state and wiring to `swee/log_tailer.py`

**Files:**
- Modify: `swee/log_tailer.py`

**Interfaces:**
- Produces: module-level `pending_connects: dict[str, asyncio.Task]` in `swee/log_tailer.py`,
  keyed by player display name.
- Produces: `async def _fallback_join(name: str, dt: datetime) -> None` in `swee/log_tailer.py`.
- Consumes: existing `broadcast_embed`, `record_join`, `update_stats_message`, `COLOR_JOIN`
  already imported in `swee/log_tailer.py`.

- [ ] **Step 1: Add `CONNECT_RE` and the `pending_connects` dict**

Edit `swee/log_tailer.py` lines 16-20. Change:

```python
JOIN_RE     = re.compile(r'\[LOG\]\s*(.+?) joined the server')
LEAVE_RE    = re.compile(r'\[LOG\]\s*(.+?) left the server')
TS_RE       = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)')
SHUTDOWN_RE = re.compile(r'Shutdown handler: initialize\.')
VERSION_RE  = re.compile(r'Game version is (v[\d.]+)')
```

to:

```python
JOIN_RE     = re.compile(r'\[LOG\]\s*(.+?) joined the server')
LEAVE_RE    = re.compile(r'\[LOG\]\s*(.+?) left the server')
CONNECT_RE  = re.compile(r'\[LOG\]\s*(.+?) [\d.]+ connected the server')
TS_RE       = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)')
SHUTDOWN_RE = re.compile(r'Shutdown handler: initialize\.')
VERSION_RE  = re.compile(r'Game version is (v[\d.]+)')

FALLBACK_JOIN_DELAY_SEC = 30

# Palworld doesn't always log "X joined the server" for a connection that
# clearly succeeded (player ends up chatting/playing) — some sessions only
# ever get a "connected" line. This tracks a per-player timer, started on
# "connected", that fires a fallback join notification unless a real
# "joined" or "left" line cancels it first.
pending_connects = {}  # display name -> asyncio.Task
```

- [ ] **Step 2: Add the `_fallback_join` coroutine**

Insert this function immediately after the `log_tailer` module's regex/state block (after the
`pending_connects = {}` line added in Step 1, before `async def log_tailer():`):

```python
async def _fallback_join(name, dt):
    await asyncio.sleep(FALLBACK_JOIN_DELAY_SEC)
    pending_connects.pop(name, None)
    await broadcast_embed(f"{name} joined the server", None, COLOR_JOIN, dt)
    await record_join(name, dt)
    await update_stats_message()
```

- [ ] **Step 3: Wire `CONNECT_RE` matching, and cancellation on `JOIN_RE`/`LEAVE_RE`, into the
  tailer loop**

Edit `swee/log_tailer.py` lines 51-61 (inside `log_tailer()`, the `ts_match` handling block).
Change:

```python
                ts_match = TS_RE.match(msg)
                if ts_match:
                    _, rest_msg = ts_match.groups()
                    if m := JOIN_RE.search(rest_msg):
                        await broadcast_embed(f"{m.group(1)} joined the server", None, COLOR_JOIN, dt)
                        await record_join(m.group(1), dt)
                        await update_stats_message()
                    elif m := LEAVE_RE.search(rest_msg):
                        await broadcast_embed(f"{m.group(1)} left the server", None, COLOR_LEAVE, dt)
                        await record_leave(m.group(1), dt)
                        await update_stats_message()
```

to:

```python
                ts_match = TS_RE.match(msg)
                if ts_match:
                    _, rest_msg = ts_match.groups()
                    if m := CONNECT_RE.search(rest_msg):
                        name = m.group(1)
                        if pending := pending_connects.pop(name, None):
                            pending.cancel()
                        pending_connects[name] = asyncio.create_task(_fallback_join(name, dt))
                    elif m := JOIN_RE.search(rest_msg):
                        name = m.group(1)
                        if pending := pending_connects.pop(name, None):
                            pending.cancel()
                        await broadcast_embed(f"{name} joined the server", None, COLOR_JOIN, dt)
                        await record_join(name, dt)
                        await update_stats_message()
                    elif m := LEAVE_RE.search(rest_msg):
                        name = m.group(1)
                        if pending := pending_connects.pop(name, None):
                            pending.cancel()
                        await broadcast_embed(f"{name} left the server", None, COLOR_LEAVE, dt)
                        await record_leave(name, dt)
                        await update_stats_message()
```

- [ ] **Step 4: Sanity-check the module imports and compiles**

Run: `python -m py_compile swee/log_tailer.py`
Expected: no output, exit code 0.

- [ ] **Step 5: Manually re-read the diff for regex-order correctness**

Run:

```bash
git diff swee/log_tailer.py
```

Confirm `CONNECT_RE` is checked before `JOIN_RE`/`LEAVE_RE` in the `if`/`elif` chain (a
`"connected the server"` line must never match `JOIN_RE` or `LEAVE_RE`, so order doesn't change
matching correctness here, but keep `CONNECT_RE` first for readability since it's the newest
branch). Confirm every branch that pops `pending_connects` also cancels the popped task before
proceeding, and that the `CONNECT_RE` branch's own scheduling line
(`pending_connects[name] = asyncio.create_task(...)`) runs after the cancel-and-pop of any prior
task for the same name.

- [ ] **Step 6: Commit**

```bash
git add swee/log_tailer.py
git commit -m "feat: add fallback join notification for missed 'joined the server' log lines"
```

---

## Final Verification

- [ ] Run `python -m py_compile swee/log_tailer.py` — expect no output, exit code 0.
- [ ] Run `python -m unittest discover tests -v` — expect the existing `palworld_settings` tests
  to still pass (this change doesn't touch that module, so this just guards against import
  breakage across the package).
- [ ] Manual verification against the live bot on `lychee` (no automated harness exists for this
  layer, per `CLAUDE.md`):
  1. Deploy the branch to a test/dev environment, or watch the live `journalctl -u
     palworld-palchuds -f` alongside the bot's own logs.
  2. Have a player connect and join normally (both `"connected"` and `"joined"` lines appear
     within a few seconds). Confirm exactly **one** join notification appears in the activity
     channel, timestamped from the real `"joined"` line — the fallback timer must not also fire.
  3. Have a player connect and immediately disconnect (or simulate by killing the client mid-load,
     if reproducible) within 30s, with no `"joined"` line. Confirm **no** join notification
     appears — only the leave, same as current behavior for bounced connections.
  4. If a genuine missed-join case is reproducible (or wait for one to occur naturally, given the
     audit found ~1 every few days): confirm a join notification appears roughly 30s after the
     `"connected"` line, using the connect event's timestamp, and that the player's join is
     correctly recorded (`player_history.json` / stats embed "Online" list reflects them).
  5. Confirm a rapid reconnect (`connected` → `connected` within 30s, no `joined`/`left` between)
     restarts the timer rather than firing twice — only one fallback notification, anchored to the
     second `connected` line's timestamp, roughly 30s after it.
- [ ] Open a PR per `CLAUDE.md` (never push directly to `main`), bundling this plan file, the spec
  (already committed), and the code change into one PR.
