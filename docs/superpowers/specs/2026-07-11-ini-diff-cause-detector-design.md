# INI-diff cause detector — design

## Problem

`detect_unplanned_restart_cause()` (added 2026-07-10) currently has one detector:
`detect_unattended_upgrades`. Any restart it doesn't recognize — including a deliberate manual
edit of `PalWorldSettings.ini` followed by a host-level `systemctl restart palworld` (not through
the bot's `/restart` command) — falls through to the generic "Unknown — an admin will need to
check the server logs" message. This happened on 2026-07-11: an admin edited the INI and
restarted the service directly, and the bot posted "Server restarted unexpectedly / Unknown"
even though the cause was sitting right there in the INI diff.

Separately, `check_palworld_settings_change()` (also added 2026-07-10) already computes and posts
this exact diff — but only later, when the server comes back online (`VERSION_RE` match), as an
independent "Palworld settings changed" embed. In the 2026-07-11 incident this second embed also
never appeared, because the restart was the *first* one since the settings-change feature shipped
(`last_palworld_settings` was still `None`), so the check silently seeded the baseline instead of
reporting anything — an intentional "don't dump a changelog on first deploy" behavior, but with no
visible signal that this is what happened, leaving the change unaccounted-for.

## Scope

- Add a new cause detector that diffs the current `PalWorldSettings.ini` against the saved
  baseline and, if different, reports the change as the "Likely cause" field on the unplanned-
  restart embed — reusing the existing diff/format functions from the settings-change feature.
- When there's no baseline yet (first-ever check), report that explicitly instead of falling
  through to "Unknown."
- Avoid double-reporting: once the shutdown-time cause detector reports an INI diff, the later
  online-time `check_palworld_settings_change()` must not post a second, redundant embed for the
  same change.

Out of scope: changing `check_palworld_settings_change()`'s own behavior for restarts that *don't*
go through the unplanned-restart path (e.g. `/restart` with an INI edit — that already suppresses
the "Server is online" message via `_bot_restart_in_progress` but still runs the settings check,
which is unaffected by this change and continues to work as today).

## Components

### 1. `detect_ini_settings_change` detector

```python
async def detect_ini_settings_change(shutdown_dt: datetime) -> tuple[str, dict] | None:
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
```

Appended to `CAUSE_DETECTORS` **after** `detect_unattended_upgrades` — the upgrade-log detector
has a tight, time-correlated match window and is the more specific signal; the INI diff is the
more general fallback, checked second.

Return type changes from `str | None` to `tuple[str, dict | None] | None`: the second element is
the new baseline to persist (`None` when there's nothing to save — the no-baseline-yet case, or
when a detector other than this one matches).

### 2. `detect_unplanned_restart_cause` — carry the pending baseline through

```python
async def detect_unplanned_restart_cause(shutdown_dt: datetime) -> tuple[str, dict | None] | None:
    for detector in CAUSE_DETECTORS:
        try:
            result = await detector(shutdown_dt)
        except Exception:
            log.exception("cause detector %s failed", detector.__name__)
            continue
        if result:
            return result
    return None
```

Existing detectors that don't care about a baseline (like `detect_unattended_upgrades`) get
updated to return `(text, None)` instead of a bare `text`.

### 3. `log_tailer()` — save baseline only after a confirmed send

```python
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

Mirrors the existing "only persist on confirmed send" pattern already used in
`check_palworld_settings_change()`. If the embed fails to send (e.g. Discord hiccup), the baseline
isn't advanced — the diff will simply be picked up again, either by this detector on the next
restart or by `check_palworld_settings_change()` when the server comes back online.

### 4. Downstream effect on `check_palworld_settings_change()`

No code change needed here. Once the baseline has been advanced by step 3, the diff this function
computes when the server comes back online (`VERSION_RE` match) will be empty, so it silently
returns without posting — no duplicate embed. This relies entirely on step 3 running first
(shutdown always precedes the next online event), which is already guaranteed by log order.

## Error handling

- Failure to read/parse the INI: caught, logged, detector returns `None` (falls through to the
  next detector / "Unknown"), same as the existing settings-change check's error handling.
- Detector-thrown exceptions: already caught generically by `detect_unplanned_restart_cause`.
- Discord send failure: baseline not advanced (see Component 3); next opportunity retries.

## Non-goals / risks accepted

- Redacted keys (`AdminPassword`, `ServerPassword`) still show as `(changed)` via the existing
  `format_settings_change_fields`, unchanged.
- If both an unattended-upgrade *and* an unrelated INI edit happen to coincide, only the upgrade
  cause is reported (detector order) and the INI baseline is *not* advanced by this code path —
  it'll still be picked up later by `check_palworld_settings_change()` on the next online event.
  Accepted as a rare edge case matching the "first non-`None` result wins" design already in place.
