import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable

from swee.config import ALERTS_CHANNEL_ID, COLOR_SHUTDOWN, PALWORLD_SETTINGS_INI_PATH
from swee.embeds import broadcast_embed
from swee.palworld_settings import diff_palworld_settings, format_settings_change_fields, parse_palworld_settings

log = logging.getLogger("swee")

# ---------- Palworld settings snapshot (settings-change alert + unplanned-restart cause) ----------
PALWORLD_SETTINGS_CACHE_PATH = "last_palworld_settings.json"
last_palworld_settings = None  # cached in-memory; mirrors last_palworld_settings.json on disk; None until first check


def load_last_palworld_settings():
    global last_palworld_settings
    try:
        with open(PALWORLD_SETTINGS_CACHE_PATH) as f:
            last_palworld_settings = json.load(f)
    except FileNotFoundError:
        last_palworld_settings = None
    except json.JSONDecodeError:
        log.warning("last_palworld_settings.json is corrupt, starting with no cached settings")
        last_palworld_settings = None


def save_last_palworld_settings(settings):
    global last_palworld_settings
    last_palworld_settings = settings
    with open(PALWORLD_SETTINGS_CACHE_PATH, "w") as f:
        json.dump(settings, f, indent=2)


async def check_palworld_settings_change():
    global last_palworld_settings
    try:
        new_settings = await asyncio.to_thread(parse_palworld_settings, PALWORLD_SETTINGS_INI_PATH)
    except Exception:
        log.warning("failed to read/parse PalWorldSettings.ini, skipping settings-change check", exc_info=True)
        return

    try:
        if last_palworld_settings is None:
            # First-ever check — seed the baseline without announcing, so shipping this
            # feature doesn't dump every existing setting as "changed" on first deploy.
            save_last_palworld_settings(new_settings)
            return

        changes = diff_palworld_settings(last_palworld_settings, new_settings)
        if not changes:
            return

        sent = await broadcast_embed(
            "Palworld settings changed",
            None,
            COLOR_SHUTDOWN,
            channel_id=ALERTS_CHANNEL_ID,
            fields=format_settings_change_fields(changes),
        )
        if sent:
            save_last_palworld_settings(new_settings)
        else:
            log.warning("settings-change alert failed to post, will retry next restart")
    except Exception:
        log.exception("settings-change check failed after parsing PalWorldSettings.ini")


# ---------- Unplanned-restart cause detection ----------
UNATTENDED_UPGRADES_LOG = "/var/log/unattended-upgrades/unattended-upgrades.log"
UPGRADE_LOG_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO Packages that will be upgraded: (.+)$'
)


def _read_last_lines(path, n):
    with open(path) as f:
        return f.readlines()[-n:]


async def detect_unattended_upgrades(shutdown_dt):
    try:
        lines = await asyncio.to_thread(_read_last_lines, UNATTENDED_UPGRADES_LOG, 100)
    except FileNotFoundError:
        return None
    except OSError:
        log.warning("cause detector: cannot read %s", UNATTENDED_UPGRADES_LOG, exc_info=True)
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


async def detect_unplanned_restart_cause(shutdown_dt):
    for detector in CAUSE_DETECTORS:
        try:
            result = await detector(shutdown_dt)
        except Exception:
            log.exception("cause detector %s failed", detector.__name__)
            continue
        if result:
            return result
    return None
