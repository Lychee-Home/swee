import difflib
import logging
import re

import httpx

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
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(WIKI_API_BASE, params={**params, "action": "cargoquery", "format": "json"})
        r.raise_for_status()
        return r.json()


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
