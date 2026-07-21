import json
import logging

import httpx
from discord.ext import tasks

from swee.config import PALFEED_CHANNEL_ID, PALFEED_SERVICE_URL
from swee.embeds import broadcast_embed
from swee.palfeed_notability import notability_tier, talent_score
from swee.player_history import resolve_owner_name

log = logging.getLogger("swee")

PALFEED_STATE_PATH = "palfeed_state.json"
PALFEED_BATCH_LIMIT = 5

ACQUISITION_VERBS = {
    "wild_capture": "caught",
    "hatched": "hatched",
    "purchased": "purchased",
}

TIER_COLORS = {
    "Lucky": 0xF1C40F,
    "Awakened": 0x1ABC9C,
    "Perfect": 0x9B59B6,
    "Excellent": 0x3498DB,
    "Great": 0x2ECC71,
}

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
    character_id = event.get("pal_name") or event.get("character_id") or "Unknown Pal"
    verb = ACQUISITION_VERBS.get(event.get("acquisition_type"), "acquired")
    owner_name = resolve_owner_name(event.get("owner_player_uid"))
    if owner_name:
        title = f"{owner_name} {verb} a {character_id} with {tier} IVs"
    else:
        title = f"A {character_id} with {tier} IVs was {verb}"

    level = event.get("level")
    level_prefix = f"Level {level} · " if level is not None else ""
    hp = event.get("talent_hp", 0)
    attack = event.get("talent_shot", 0)
    defense = event.get("talent_defense", 0)
    total = talent_score(event)
    percent = round(total / 300 * 100)

    fields = [
        ("IV%", f"{percent}%"),
        ("Stats", f"{level_prefix}{hp} HP / {attack} Attack / {defense} Defense"),
    ]

    return title, fields


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
            title, fields = format_catch_embed(event, tier)
            sent = await broadcast_embed(
                title, None, TIER_COLORS[tier], channel_id=PALFEED_CHANNEL_ID,
                fields=fields, fields_inline=False,
            )
            if not sent:
                log.warning("palfeed announcement failed for event %s, will retry next tick", event["id"])
                break
        save_last_event_id(event["id"])
