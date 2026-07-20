import json
import logging

import httpx
from discord.ext import tasks

from swee.config import COLOR_PALFEED, PALFEED_CHANNEL_ID, PALFEED_SERVICE_URL
from swee.embeds import broadcast_embed
from swee.palfeed_notability import ACQUISITION_LABELS, notability_tier, talent_score

log = logging.getLogger("swee")

PALFEED_STATE_PATH = "palfeed_state.json"
PALFEED_BATCH_LIMIT = 5

last_event_id = 0  # cached in-memory; mirrors palfeed_state.json on disk


def load_last_event_id():
    global last_event_id
    try:
        with open(PALFEED_STATE_PATH) as f:
            last_event_id = json.load(f).get("last_event_id", 0)
    except FileNotFoundError:
        last_event_id = 0
    except json.JSONDecodeError:
        log.warning("palfeed_state.json is corrupt, starting with no cached cursor")
        last_event_id = 0


def save_last_event_id(event_id):
    global last_event_id
    last_event_id = event_id
    with open(PALFEED_STATE_PATH, "w") as f:
        json.dump({"last_event_id": event_id}, f, indent=2)


async def fetch_new_pal_events(since, limit):
    url = f"{PALFEED_SERVICE_URL}/events/new-pals"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, params={"since": since, "limit": limit})
        r.raise_for_status()
        return r.json()


def format_catch_embed(event, tier):
    title = f"{event.get('character_id') or 'Unknown Pal'} — {tier}"
    acquisition = ACQUISITION_LABELS.get(event.get("acquisition_type"), "Acquired")
    level = event.get("level")
    description = acquisition + (f" — Level {level}" if level is not None else "")
    fields = [("Talent Score", f"{talent_score(event)}/300")]
    return title, description, fields


@tasks.loop(seconds=60)
async def palfeed_ticker():
    try:
        events = await fetch_new_pal_events(last_event_id, PALFEED_BATCH_LIMIT)
    except Exception:
        log.exception("palfeed poll failed")
        return

    for event in events:
        tier = notability_tier(event)
        if tier:
            title, description, fields = format_catch_embed(event, tier)
            sent = await broadcast_embed(
                title, description, COLOR_PALFEED, channel_id=PALFEED_CHANNEL_ID, fields=fields,
            )
            if not sent:
                log.warning("palfeed announcement failed for event %s, will retry next tick", event["id"])
                break
        save_last_event_id(event["id"])
