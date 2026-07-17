import difflib
import json
import logging
import re
import time

import httpx
from anthropic import AsyncAnthropic

from swee.config import ANTHROPIC_API_KEY, ASK_COOLDOWN_SEC, ASSISTANT_LOG_CHANNEL_ID, COLOR_CHAT
from swee.embeds import broadcast_embed
from swee.rest_client import rest

log = logging.getLogger("swee")

MENTION_RE = re.compile(r'^@swee\b\s*(.*)', re.IGNORECASE)
WIKI_API_BASE = "https://palworld.wiki.gg/api.php"

ASPECT_TABLES = {
    "breeding": ("PalBreeding", "palName", ["palName", "breedingRank", "maleProbability", "isUniqueCombo", "palEgg"]),
    "drops": ("DropDefeat", "targetName", ["targetName", "itemName", "chance", "minQty", "maxQty"]),
    "work_suitability": ("PalWorkSuitability", "palName", ["palName", "workType", "level"]),
    "stats": ("PalStat", "palName", ["palName", "baseHp", "baseAttack", "baseDefense", "baseWorkSpeed"]),
    "passive_skills": ("PalPassiveSkill", "palName", ["palName", "passiveSkillName"]),
}

_known_pal_names = []


def parse_mention(chat_text):
    m = MENTION_RE.match(chat_text.strip())
    if not m:
        return None
    question = m.group(1).strip()
    return question or None


def is_on_cooldown(name, last_answered, cooldown_sec, now):
    last = last_answered.get(name)
    return last is not None and now - last < cooldown_sec


def record_answered(name, last_answered, now):
    last_answered[name] = now


def fuzzy_match_pal_name(query, known_names):
    if not known_names:
        return None
    lowered = {n.lower(): n for n in known_names}
    if query.lower() in lowered:
        return lowered[query.lower()]
    matches = difflib.get_close_matches(query.lower(), lowered.keys(), n=1, cutoff=0.6)
    return lowered[matches[0]] if matches else None


async def _cargoquery(params):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(WIKI_API_BASE, params={**params, "action": "cargoquery", "format": "json"})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError:
        return {"error": "wiki lookup failed"}


async def get_known_pal_names():
    global _known_pal_names
    if not _known_pal_names:
        data = await _cargoquery({"tables": "Pal", "fields": "palName", "limit": "500"})
        _known_pal_names = [row["title"]["palName"] for row in data.get("cargoquery", [])]
    return _known_pal_names


async def lookup_pal(pal_name, aspect):
    if aspect not in ASPECT_TABLES:
        return {"error": f"unknown aspect '{aspect}'"}
    table, name_field, fields = ASPECT_TABLES[aspect]
    known_names = await get_known_pal_names()
    matched = fuzzy_match_pal_name(pal_name, known_names)
    if matched is None:
        return {"error": f"no pal found matching '{pal_name}'"}
    data = await _cargoquery({
        "tables": table,
        "fields": ",".join(fields),
        "where": f'{name_field}="{matched}"',
    })
    rows = [row["title"] for row in data.get("cargoquery", [])]
    if not rows:
        return {"error": f"no {aspect} data found for {matched}"}
    return {"pal": matched, "aspect": aspect, "data": rows}


ASSISTANT_SYSTEM_PROMPT = (
    "You are swee, a Discord bot answering Palworld questions asked by players in-game chat. "
    "Your reply is broadcast to every player on the server, so keep it to one short sentence. "
    "For anything about a specific pal — breeding, drops, work suitability, stats, or passive "
    "skills — call the lookup_pal tool rather than guessing exact values. For broader strategy or "
    "general mechanics questions the tool can't answer, use your own Palworld knowledge, but don't "
    "invent specific numbers you're not sure of. If the question isn't about Palworld, reply that "
    "you can only help with Palworld questions."
)

LOOKUP_PAL_TOOL = {
    "name": "lookup_pal",
    "description": "Look up structured data about a specific Palworld pal from the live wiki database.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pal_name": {"type": "string", "description": "The pal's name, e.g. 'Lamball'"},
            "aspect": {
                "type": "string",
                "enum": list(ASPECT_TABLES.keys()),
                "description": "Which kind of data to fetch",
            },
        },
        "required": ["pal_name", "aspect"],
    },
}

_anthropic = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


async def ask_claude(question):
    messages = [{"role": "user", "content": question}]
    for _ in range(3):
        response = await _anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=ASSISTANT_SYSTEM_PROMPT,
            tools=[LOOKUP_PAL_TOOL],
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            text = "".join(block.text for block in response.content if block.type == "text").strip()
            return text or "Sorry, I couldn't figure that one out."
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = await lookup_pal(block.input["pal_name"], block.input["aspect"])
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)})
        messages.append({"role": "user", "content": tool_results})
    return "Sorry, I couldn't figure that one out."


_last_answered = {}


async def handle_mention(player_name, question):
    if _anthropic is None:
        return
    now = time.monotonic()
    if is_on_cooldown(player_name, _last_answered, ASK_COOLDOWN_SEC, now):
        return
    record_answered(player_name, _last_answered, now)
    try:
        answer = await ask_claude(question)
    except Exception:
        log.exception("assistant: failed to answer question from %s", player_name)
        answer = "Sorry, I couldn't look that up right now."
    try:
        await rest.announce(f"[swee] {answer}")
    except Exception:
        log.exception("assistant: announce failed")
    if ASSISTANT_LOG_CHANNEL_ID:
        await broadcast_embed(
            f"{player_name} asked swee",
            f"**Q:** {question}\n**A:** {answer}",
            COLOR_CHAT,
            channel_id=ASSISTANT_LOG_CHANNEL_ID,
        )
