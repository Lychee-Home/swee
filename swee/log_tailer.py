import asyncio
import json
import logging
import re
from datetime import datetime, timezone

import swee.restart as restart_module
from swee.cause_detection import check_palworld_settings_change, detect_unplanned_restart_cause, save_last_palworld_settings
from swee.config import ALERTS_CHANNEL_ID, COLOR_JOIN, COLOR_LEAVE, COLOR_READY, COLOR_SHUTDOWN, PACIFIC, PALWORLD_SERVICE_NAME
from swee.embeds import broadcast_embed
from swee.player_history import record_join, record_leave
from swee.stats import update_stats_message

log = logging.getLogger("swee")

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


async def _fallback_join(name, dt):
    await asyncio.sleep(FALLBACK_JOIN_DELAY_SEC)
    pending_connects.pop(name, None)
    try:
        await broadcast_embed(f"{name} joined the server", None, COLOR_JOIN, dt)
        await record_join(name, dt)
        await update_stats_message()
    except Exception:
        log.exception("fallback join broadcast failed for player %s", name)


async def log_tailer():
    # journalctl can exit on its own (log rotation, service hiccup, etc.); without
    # this loop a single exit would silently kill the relay for good.
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                "journalctl", "-u", PALWORLD_SERVICE_NAME, "-f", "-n", "0", "-o", "json", "--no-pager",
                stdout=asyncio.subprocess.PIPE,
            )
            assert proc.stdout is not None
            async for line in proc.stdout:
                line = line.decode().strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = entry.get("MESSAGE", "")
                if isinstance(msg, list):
                    msg = " ".join(str(m) for m in msg)
                if not isinstance(msg, str):
                    continue

                micros = int(entry.get("__REALTIME_TIMESTAMP", 0))
                dt = datetime.fromtimestamp(micros / 1_000_000, tz=timezone.utc).astimezone(PACIFIC)

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
                else:
                    if SHUTDOWN_RE.search(msg):
                        if restart_module._bot_restart_in_progress:
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
                    elif m := VERSION_RE.search(msg):
                        await broadcast_embed("Server is online", f"Game version: `{m.group(1)}`", COLOR_READY, dt, channel_id=ALERTS_CHANNEL_ID)
                        await check_palworld_settings_change()
            log.warning("log tailer: journalctl stream ended, restarting in 5s")
        except Exception:
            log.exception("log tailer crashed, restarting in 5s")
        await asyncio.sleep(5)
