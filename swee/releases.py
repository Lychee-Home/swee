import json
import logging
import re
from datetime import datetime, timezone

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

# release-please's top-of-body header, e.g. "## [2.5.0](compare-url) (2026-07-17)" (or, for a
# repo's very first release with no prior tag to compare against, "## 2.5.0 (2026-07-17)").
RELEASE_HEADER_RE = re.compile(
    r'^##\s+(?:\[(?P<version_linked>[^\]]+)\]\([^)]*\)|(?P<version_plain>\S+))'
    r'\s*\((?P<date>\d{4}-\d{2}-\d{2})\)\s*$'
)


def parse_release_header(body):
    for line in body.splitlines():
        m = RELEASE_HEADER_RE.match(line.strip())
        if not m:
            continue
        version = m.group("version_linked") or m.group("version_plain")
        date = datetime.strptime(m.group("date"), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return version, date
    return None, None


def parse_release_timestamp(published_at):
    # GitHub's release `published_at` is an ISO 8601 UTC timestamp, e.g.
    # "2026-07-17T10:00:00Z" — the actual time the release was published, unlike the date in the
    # release-please changelog header (which is when the release-please PR was generated/merged
    # and can lag behind, especially for backlog announcements sent well after the fact).
    if not published_at:
        return None
    return datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def select_missed_releases(releases, last_tag):
    # releases is newest-first (GitHub API order). Stop as soon as last_tag is found; if it's
    # never found (backlog bigger than one page), every entry here counts as missed.
    missed = []
    for release in releases:
        if release.get("tag_name") == last_tag:
            break
        missed.append(release)
    missed.reverse()
    return missed


# Matches env var names like GITHUB_REPO or PALWORLD_SETTINGS_INI_PATH: internal bot config that
# means nothing to players, so bullets mentioning one are dropped from the announcement.
ENV_VAR_MENTION_RE = re.compile(r'\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b')

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


async def fetch_releases():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=headers, params={"per_page": 100})
        r.raise_for_status()
        # /releases (unlike /releases/latest) returns drafts and prereleases too — filter them
        # out here so every caller sees only published, non-prerelease releases, matching what
        # /releases/latest always guaranteed before this endpoint swap.
        return [rel for rel in r.json() if not rel.get("draft") and not rel.get("prerelease")]


def humanize_release_notes(body):
    version, _ = parse_release_header(body)
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
        if ENV_VAR_MENTION_RE.search(desc):
            continue
        if desc:
            desc = desc[0].upper() + desc[1:]
        grouped.setdefault(label, []).append(desc)

    if not grouped:
        return None

    sections = []
    if version:
        sections.append(f"**{version}**")
    for label in RELEASE_NOTE_SECTION_ORDER:
        if label in grouped:
            lines = "\n".join(f"• {d}" for d in grouped[label])
            sections.append(f"**{label}**\n{lines}")
    return "\n\n".join(sections)


@tasks.loop(minutes=5)
async def release_ticker():
    global last_release_tag
    try:
        releases = await fetch_releases()
    except Exception:
        log.exception("release check failed")
        return

    if not releases:
        return

    newest_tag = releases[0].get("tag_name")
    if not newest_tag:
        return

    if last_release_tag is None:
        # First run with no cached state — seed it without announcing, so
        # shipping this feature doesn't dump a changelog for releases that
        # already happened before the bot could track them.
        save_last_release(newest_tag)
        return

    if newest_tag == last_release_tag:
        return

    for release in select_missed_releases(releases, last_release_tag):
        tag = release.get("tag_name")
        if not tag:
            continue
        body = release.get("body") or ""
        release_date = parse_release_timestamp(release.get("published_at"))
        notes = humanize_release_notes(body)
        if notes is None:
            notes = body or "No release notes."
            max_len = 4000
            if len(notes) > max_len:
                notes = notes[:max_len] + "…"
        sent = await broadcast_embed(
            "New Release",
            notes,
            COLOR_READY,
            dt=release_date,
            channel_id=BOT_UPDATES_CHANNEL_ID,
        )
        if sent:
            save_last_release(tag)
        else:
            log.warning("release announcement failed for %s, will retry next tick", tag)
            break
