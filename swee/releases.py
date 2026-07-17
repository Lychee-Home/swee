import json
import logging
import re

import httpx
from discord.ext import tasks

from swee.config import BOT_UPDATES_CHANNEL_ID, COLOR_READY, GITHUB_REPO, GITHUB_TOKEN
from swee.embeds import broadcast_embed

log = logging.getLogger("swee")

# release-please's changelog format groups bullets under "### <Section>" headers rather than
# prefixing each line with a Conventional Commit type, and appends " ([#N](url)) ([sha](url))"
# link references to each bullet instead of GitHub's auto-generated "by @user in url" suffix.
RELEASE_NOTE_SECTION_RE = re.compile(r'^###\s+(?P<section>.+?)\s*$')
RELEASE_NOTE_BULLET_RE = re.compile(
    r'^\*\s*(?P<desc>.+?)\s*(?:\(\[[^\]]+\]\([^)]+\)\)\s*)*$'
)
RELEASE_NOTE_LABELS = {"Features": "New", "Bug Fixes": "Fixes", "Performance Improvements": "Fixes"}
# Section display order, derived from RELEASE_NOTE_LABELS itself (first-appearance order,
# de-duplicated) so the two never drift apart.
RELEASE_NOTE_SECTION_ORDER = tuple(dict.fromkeys(RELEASE_NOTE_LABELS.values()))

LAST_RELEASE_PATH = "last_release.json"
last_release_tag = None  # cached in-memory; mirrors last_release.json on disk


def load_last_release():
    global last_release_tag
    try:
        with open(LAST_RELEASE_PATH) as f:
            last_release_tag = json.load(f).get("tag")
    except FileNotFoundError:
        last_release_tag = None
    except json.JSONDecodeError:
        log.warning("last_release.json is corrupt, starting with no cached tag")
        last_release_tag = None


def save_last_release(tag):
    global last_release_tag
    last_release_tag = tag
    with open(LAST_RELEASE_PATH, "w") as f:
        json.dump({"tag": tag}, f, indent=2)


async def fetch_latest_release():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


def humanize_release_notes(body):
    grouped = {}
    label = None
    for line in body.splitlines():
        line = line.strip()
        section_match = RELEASE_NOTE_SECTION_RE.match(line)
        if section_match:
            label = RELEASE_NOTE_LABELS.get(section_match.group("section"))
            continue
        if not label:
            continue
        bullet_match = RELEASE_NOTE_BULLET_RE.match(line)
        if not bullet_match:
            continue
        desc = bullet_match.group("desc").strip()
        if desc:
            desc = desc[0].upper() + desc[1:]
        grouped.setdefault(label, []).append(desc)

    if not grouped:
        return None

    sections = []
    for label in RELEASE_NOTE_SECTION_ORDER:
        if label in grouped:
            lines = "\n".join(f"• {d}" for d in grouped[label])
            sections.append(f"**{label}**\n{lines}")
    return "\n\n".join(sections)


@tasks.loop(minutes=5)
async def release_ticker():
    global last_release_tag
    try:
        release = await fetch_latest_release()
    except Exception:
        log.exception("release check failed")
        return

    tag = release.get("tag_name")
    if not tag:
        return

    if last_release_tag is None:
        # First run with no cached state — seed it without announcing, so
        # shipping this feature doesn't dump a changelog for a release that
        # already happened before the bot could track it.
        save_last_release(tag)
        return

    if tag == last_release_tag:
        return

    body = release.get("body") or ""
    notes = humanize_release_notes(body)
    if notes is None:
        notes = body or "No release notes."
        max_len = 4000
        if len(notes) > max_len:
            notes = notes[:max_len] + "…"
    sent = await broadcast_embed(
        f"{tag} released",
        notes,
        COLOR_READY,
        channel_id=BOT_UPDATES_CHANNEL_ID,
    )
    if sent:
        save_last_release(tag)
    else:
        log.warning("release announcement failed for %s, will retry next tick", tag)
