# INI-Diff Cause Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an unplanned Palworld restart's cause is a `PalWorldSettings.ini` edit, report the actual diff as the "Likely cause" instead of falling through to "Unknown" — and make sure that diff isn't then reported a second time when the server comes back online.

**Architecture:** All changes live in the existing single-file `main.py` (per `CLAUDE.md`, no package split without asking). A new cause detector, `detect_ini_settings_change`, is appended to `CAUSE_DETECTORS`, reusing the existing `parse_palworld_settings` / `diff_palworld_settings` / `format_settings_change_fields` functions already shipped for the settings-change-alert feature. Cause detectors now return `tuple[str, dict | None] | None` instead of `str | None` — the second tuple element is a settings baseline to persist, used only by this new detector. `log_tailer`'s `SHUTDOWN_RE` branch unpacks that tuple and saves the baseline via the existing `save_last_palworld_settings`, but only after `broadcast_embed` confirms the embed sent — so a Discord hiccup doesn't silently drop the diff. Once the baseline is current, `check_palworld_settings_change()`'s later diff (on the server-online event) finds nothing changed and stays silent, avoiding a duplicate embed.

**Tech Stack:** Python 3.14, discord.py, asyncio. No test framework in this repo.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-11-ini-diff-cause-detector-design.md` — every requirement below traces back to it.
- No automated test runner exists in this repo (see `CLAUDE.md`). Verification uses `python -m py_compile main.py` for syntax, standalone `python` scratch scripts (copied logic, since `main.py` cannot be imported without a real `.env`/Discord token/Linux host) for pure/isolable logic, and manual trace review for parts that need Discord/systemd/journalctl at runtime.
- `main.py` only runs on Linux, on the same host as the Palworld server — it cannot be run end-to-end in this development environment (Windows). Do not attempt to `python main.py` here.
- New detector's no-baseline message is exactly: `"Settings-change tracking just initialized — no prior baseline to compare against."`
- Reuse `format_settings_change_fields` for per-key formatting (including the `AdminPassword`/`ServerPassword` redaction it already does) — do not reimplement.
- Cause text placed in a single Discord embed field value — must stay under Discord's 1024-character field-value limit; truncate with `…` if exceeded.
- Detector order in `CAUSE_DETECTORS`: `detect_unattended_upgrades` first, `detect_ini_settings_change` second.
- Baseline is only persisted after a confirmed `broadcast_embed` send (mirrors the existing pattern in `check_palworld_settings_change()`).
- Keep everything in `main.py` — no new files, no new dependencies.

---

### Task 1: Add `detect_ini_settings_change` and switch detector return type to `(text, settings)` tuples

**Files:**
- Modify: `main.py:713-734` (`detect_unattended_upgrades`)
- Modify: `main.py:737-739` (`CAUSE_DETECTORS` registry + its type annotation)

**Interfaces:**
- Consumes: `parse_palworld_settings` (`main.py:101`), `PALWORLD_SETTINGS_INI_PATH` (`main.py:37`), `last_palworld_settings` (`main.py:252`), `diff_palworld_settings` (`main.py:277`), `format_settings_change_fields` (`main.py:286`) — all pre-existing.
- Produces: `async def detect_ini_settings_change(shutdown_dt) -> tuple[str, dict | None] | None`, used by Task 2 via the updated `CAUSE_DETECTORS`/`detect_unplanned_restart_cause`. Also changes `detect_unattended_upgrades`'s return shape on match from `str` to `tuple[str, None]` (its "no match" paths remain bare `None`, unchanged) — Task 2's caller must handle this new shape.

- [ ] **Step 1: Change `detect_unattended_upgrades`'s match case to return a tuple**

Replace `main.py:713-734`:

```python
async def detect_unattended_upgrades(shutdown_dt):
    try:
        lines = await asyncio.to_thread(_read_last_lines, UNATTENDED_UPGRADES_LOG, 100)
    except OSError:
        return None

    for line in reversed(lines):
        m = UPGRADE_LOG_RE.match(line.strip())
        if not m:
            continue
        try:
            # unattended-upgrades logs in system local time; assumes the host runs in UTC
            # (true for this deployment) — if that changes, this comparison silently stops
            # matching and just degrades to "cause unknown" rather than erroring.
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        delta = (shutdown_dt.astimezone(timezone.utc) - ts).total_seconds()
        if -30 <= delta <= 120:
            return "A routine system update installed a security patch that caused a restart."
        return None  # most recent entry too far from the shutdown time — no match
    return None
```

with:

```python
async def detect_unattended_upgrades(shutdown_dt):
    try:
        lines = await asyncio.to_thread(_read_last_lines, UNATTENDED_UPGRADES_LOG, 100)
    except OSError:
        return None

    for line in reversed(lines):
        m = UPGRADE_LOG_RE.match(line.strip())
        if not m:
            continue
        try:
            # unattended-upgrades logs in system local time; assumes the host runs in UTC
            # (true for this deployment) — if that changes, this comparison silently stops
            # matching and just degrades to "cause unknown" rather than erroring.
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        delta = (shutdown_dt.astimezone(timezone.utc) - ts).total_seconds()
        if -30 <= delta <= 120:
            return "A routine system update installed a security patch that caused a restart.", None
        return None  # most recent entry too far from the shutdown time — no match
    return None
```

- [ ] **Step 2: Add `detect_ini_settings_change` and register it**

Replace `main.py:737-739`:

```python
CAUSE_DETECTORS: list[Callable[[datetime], Awaitable[str | None]]] = [
    detect_unattended_upgrades,
]
```

with:

```python
async def detect_ini_settings_change(shutdown_dt):
    try:
        new_settings = await asyncio.to_thread(parse_palworld_settings, PALWORLD_SETTINGS_INI_PATH)
    except Exception:
        log.warning("cause detector: failed to read/parse PalWorldSettings.ini", exc_info=True)
        return None

    if last_palworld_settings is None:
        return "Settings-change tracking just initialized — no prior baseline to compare against.", None

    changes = diff_palworld_settings(last_palworld_settings, new_settings)
    if not changes:
        return None

    lines = [f"**{k}**: {v}" for k, v in format_settings_change_fields(changes)]
    cause = "\n".join(lines)
    if len(cause) > 1024:  # Discord embed field value limit
        cause = cause[:1000] + "…"
    return cause, new_settings


CAUSE_DETECTORS: list[Callable[[datetime], Awaitable[tuple[str, dict | None] | None]]] = [
    detect_unattended_upgrades,
    detect_ini_settings_change,
]
```

- [ ] **Step 3: Verify syntax**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0.

- [ ] **Step 4: Verify the pure diff/format logic in isolation**

`main.py` can't be imported without a real `.env`/Discord token, so verify `detect_ini_settings_change`'s branching by copying its logic into a throwaway script with a faked settings-parser and faked global state.

Create `C:\Users\byron\AppData\Local\Temp\claude\C--Users-byron-PycharmProjects-swee\942e4782-a49e-481b-a919-07029893cb58\scratchpad\test_detect_ini_settings_change.py`:

```python
import asyncio


def diff_palworld_settings(old, new):
    changes = []
    for key in sorted(set(old) | set(new)):
        old_val, new_val = old.get(key), new.get(key)
        if old_val != new_val:
            changes.append((key, old_val, new_val))
    return changes


REDACTED_SETTINGS_KEYS = {"AdminPassword", "ServerPassword"}


def format_settings_change_fields(changes):
    fields = []
    display_limit = 24 if len(changes) > 25 else len(changes)
    for key, old_val, new_val in changes[:display_limit]:
        if key in REDACTED_SETTINGS_KEYS:
            display = "(changed)"
        else:
            display = f"{old_val if old_val is not None else '—'} → {new_val if new_val is not None else '—'}"
        fields.append((key, display))
    if len(changes) > 25:
        fields.append(("…", f"+{len(changes) - 24} more changed (see server config)"))
    return fields


async def detect_ini_settings_change(shutdown_dt, new_settings, last_palworld_settings, parse_should_fail=False):
    if parse_should_fail:
        return None

    if last_palworld_settings is None:
        return "Settings-change tracking just initialized — no prior baseline to compare against.", None

    changes = diff_palworld_settings(last_palworld_settings, new_settings)
    if not changes:
        return None

    lines = [f"**{k}**: {v}" for k, v in format_settings_change_fields(changes)]
    cause = "\n".join(lines)
    if len(cause) > 1024:
        cause = cause[:1000] + "…"
    return cause, new_settings


# No baseline yet -> explicit "just initialized" message, nothing to persist
result = asyncio.run(detect_ini_settings_change(None, {"DayTimeSpeedRate": "2.0"}, None))
assert result == ("Settings-change tracking just initialized — no prior baseline to compare against.", None), result

# Baseline present, one value changed -> diff text + new_settings to persist
old = {"DayTimeSpeedRate": "1.0", "ExpRate": "1.0"}
new = {"DayTimeSpeedRate": "2.0", "ExpRate": "1.0"}
result = asyncio.run(detect_ini_settings_change(None, new, old))
assert result == ("**DayTimeSpeedRate**: 1.0 → 2.0", new), result

# Baseline present, no differences -> None (falls through to next detector / Unknown)
result = asyncio.run(detect_ini_settings_change(None, old, dict(old)))
assert result is None, result

# Redacted key still redacted in the cause text
old_pw = {"AdminPassword": "old"}
new_pw = {"AdminPassword": "new"}
result = asyncio.run(detect_ini_settings_change(None, new_pw, old_pw))
assert result == ("**AdminPassword**: (changed)", new_pw), result

# Parse failure -> None (falls through), regardless of baseline state
result = asyncio.run(detect_ini_settings_change(None, {}, old, parse_should_fail=True))
assert result is None, result

print("all detect_ini_settings_change cases passed")
```

Run: `python test_detect_ini_settings_change.py` (from the scratchpad directory)
Expected output: `all detect_ini_settings_change cases passed`

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "$(cat <<'EOF'
Add INI-diff cause detector for unplanned restarts

Reuses the existing settings-diff/format functions so a manual
PalWorldSettings.ini edit followed by a host-level restart reports
the actual diff as "Likely cause" instead of falling through to
"Unknown". Also covers the case where no baseline exists yet (e.g.
right after this feature or the settings-change-alert feature ships)
with an explicit message instead of silence.
EOF
)"
```

---

### Task 2: Wire `log_tailer` to unpack the tuple and persist the baseline on confirmed send

**Files:**
- Modify: `main.py:681-693` (the `SHUTDOWN_RE` branch inside `log_tailer`)

**Interfaces:**
- Consumes: `detect_unplanned_restart_cause` (now returning `tuple[str, dict | None] | None`, from Task 1), `broadcast_embed` (`main.py:177`, already returns the sent `discord.Message` or `None` on failure), `save_last_palworld_settings` (`main.py:267`).
- Produces: nothing new for later tasks — this is the final wiring.

- [ ] **Step 1: Replace the `SHUTDOWN_RE` branch**

Replace `main.py:681-693`:

```python
                    if SHUTDOWN_RE.search(msg):
                        if _bot_restart_in_progress:
                            await broadcast_embed("Server shutting down", None, COLOR_SHUTDOWN, dt, channel_id=ALERTS_CHANNEL_ID)
                        else:
                            cause = await detect_unplanned_restart_cause(dt)
                            await broadcast_embed(
                                "Server restarted unexpectedly",
                                None,
                                COLOR_SHUTDOWN,
                                dt,
                                channel_id=ALERTS_CHANNEL_ID,
                                fields=[("Likely cause", cause or "Unknown — an admin will need to check the server logs.")],
                            )
```

with:

```python
                    if SHUTDOWN_RE.search(msg):
                        if _bot_restart_in_progress:
                            await broadcast_embed("Server shutting down", None, COLOR_SHUTDOWN, dt, channel_id=ALERTS_CHANNEL_ID)
                        else:
                            cause_result = await detect_unplanned_restart_cause(dt)
                            cause_text, pending_settings = cause_result or (None, None)
                            sent = await broadcast_embed(
                                "Server restarted unexpectedly",
                                None,
                                COLOR_SHUTDOWN,
                                dt,
                                channel_id=ALERTS_CHANNEL_ID,
                                fields=[("Likely cause", cause_text or "Unknown — an admin will need to check the server logs.")],
                            )
                            if sent and pending_settings is not None:
                                save_last_palworld_settings(pending_settings)
```

- [ ] **Step 2: Verify syntax**

Run: `python -m py_compile main.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Manual trace review (no test runner available)**

Re-read the edited branch and the functions it calls, and confirm against the spec (`docs/superpowers/specs/2026-07-11-ini-diff-cause-detector-design.md`):
- `detect_unplanned_restart_cause` (`main.py:742-751`) is unchanged — it just forwards whatever the first matching detector returns, and both detectors now consistently return `tuple[str, dict | None]` on match / `None` on no match, so `cause_result or (None, None)` correctly unpacks both the match and no-match cases.
- `pending_settings` is only non-`None` when `detect_ini_settings_change` matched with an actual diff (not the no-baseline case, which returns `None` as its second element) — so `save_last_palworld_settings` is only called when there's a real new baseline to persist.
- The baseline save happens strictly after `broadcast_embed` returns a truthy (sent) result — if the Discord send fails, `last_palworld_settings` is left untouched, so the diff will be picked up again on the next restart's `detect_ini_settings_change` call, or by `check_palworld_settings_change()` when the server next comes online.
- Once `save_last_palworld_settings` has run here, `check_palworld_settings_change()` (`main.py:607-638`) — triggered later by the same restart's `VERSION_RE` match — will compute an empty diff against the now-current baseline and silently return, so no duplicate "Palworld settings changed" embed appears for the same change.
- The `detect_unattended_upgrades` match path and the "no cause found" path both still result in `pending_settings is None`, so this new save logic is a no-op for every case except an actual INI diff — behavior for all previously-existing scenarios (planned restart, unattended-upgrades cause, truly unknown cause) is unchanged.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "$(cat <<'EOF'
Persist INI baseline after reporting it as an unplanned-restart cause

Prevents check_palworld_settings_change() from posting a duplicate
"Palworld settings changed" embed for a diff already surfaced as the
"Likely cause" of the unplanned-restart alert.
EOF
)"
```

---

## Post-plan manual smoke test (run on the actual Palworld host, not in this dev environment)

This cannot be automated here since `main.py` requires Linux, `journalctl`, `systemctl`, and a live Discord connection. After deploying, verify on the real host:

1. Edit a non-sensitive value in `PalWorldSettings.ini` (e.g. `DayTimeSpeedRate`), then restart the service directly (`sudo systemctl restart palworld`, not `/restart`). Confirm the alerts channel shows "Server restarted unexpectedly" with a "Likely cause" field containing `**DayTimeSpeedRate**: <old> → <new>` — not "Unknown".
2. Wait for the server to fully come back online (the "Game version" log line). Confirm **no** second "Palworld settings changed" embed appears — the diff was already reported in step 1 and the baseline was advanced.
3. With no INI changes and no pending package upgrades, manually stop and start the service outside any detector's window. Confirm the alerts channel still shows "Likely cause: Unknown — an admin will need to check the server logs." (unchanged fallback behavior).
4. If feasible, temporarily rename/move `last_palworld_settings.json` to simulate "no baseline yet", then restart the service after an INI edit. Confirm the cause reads "Settings-change tracking just initialized — no prior baseline to compare against." instead of showing a diff or "Unknown". Restore the file (or let it re-seed) afterward.
