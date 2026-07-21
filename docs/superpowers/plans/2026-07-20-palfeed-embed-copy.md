# palfeed Embed Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `swee/palfeed.py`'s `format_catch_embed` to produce a personalized narrative title ("Kippei caught a Lucky Foxparks") and a talent-breakdown description, replacing the current data-dump title + separate `Talent Score`/`Owner` fields.

**Architecture:** Single-function rewrite in `swee/palfeed.py`, plus removing the now-unused `ACQUISITION_LABELS` dict from `swee/palfeed_notability.py` (replaced by a verb-only mapping that lives in `palfeed.py` itself, since it's presentation copy specific to `format_catch_embed`, not notability-scoring logic).

**Tech Stack:** Python 3.14.

## Global Constraints

- Title, owner known: `"{owner} {verb} {article} {tier} {character_id}"`, e.g. `"Kippei caught a Lucky Foxparks"`.
- Title, owner unresolved (rare — `resolve_owner_name` returns `None`): `"{Article} {tier} {character_id} was {verb}"`, e.g. `"A Perfect Quivern was caught"` (article capitalized since it's now sentence-initial).
- Verb by `acquisition_type`: `wild_capture`→`"caught"`, `hatched`→`"hatched"`, `purchased`→`"purchased"` (unrecognized type falls back to `"acquired"`). Same word serves both the owner-known active form and the owner-unknown passive form — all three are valid past participles unchanged.
- Article by tier (fixed lookup, not general vowel-detection — only 5 tier strings exist and the article precedes the tier word, not the species name): `Lucky`→`"a"`, `Awakened`→`"an"`, `Perfect`→`"a"`, `Excellent`→`"an"`, `Great`→`"a"`.
- Description: `"Level {level} · {talent_hp} HP / {talent_shot} Attack / {talent_defense} Defense — {total}/300 IVs"`, where `total` is `talent_score(event)`. The `"Level {level} · "` prefix is omitted entirely when `level` is `None` (hatched pals).
- `format_catch_embed` returns a 2-tuple `(title, description)` — no more `fields` return value. `palfeed_ticker`'s `broadcast_embed(...)` call drops the `fields=fields` argument accordingly.
- Display copy only — `talent_hp`/`talent_shot`/`talent_defense`/`level`/`acquisition_type` field names in the event data are unchanged; "IVs"/"Attack" are swee-side labels, not `palsave-api`'s wire format.
- No new automated test file — per the approved design spec, this is presentation constants specific to one function, not reusable pure logic. Verify with the manual script in Step 3 instead.

---

### Task 1: Rewrite format_catch_embed

**Files:**
- Modify: `swee/palfeed_notability.py` (remove `ACQUISITION_LABELS`)
- Modify: `swee/palfeed.py` (import, new constants, `format_catch_embed`, `palfeed_ticker`)

**Interfaces:**
- Consumes: `swee.palfeed_notability.notability_tier`, `swee.palfeed_notability.talent_score` (unchanged); `swee.player_history.resolve_owner_name` (unchanged).
- Produces: `swee.palfeed.format_catch_embed(event: dict, tier: str) -> tuple[str, str]` (title, description) — changed from a 3-tuple to a 2-tuple; the only caller, `palfeed_ticker` (same file), is updated in this same task.

- [ ] **Step 1: Remove ACQUISITION_LABELS from swee/palfeed_notability.py**

Change:

```python
TALENT_TIERS = (
    (300, "Perfect"),
    (280, "Excellent"),
    (250, "Great"),
)

ACQUISITION_LABELS = {
    "wild_capture": "Caught in the wild",
    "hatched": "Hatched from an egg",
    "purchased": "Purchased from a merchant",
}


def talent_score(event: dict) -> int:
```

to:

```python
TALENT_TIERS = (
    (300, "Perfect"),
    (280, "Excellent"),
    (250, "Great"),
)


def talent_score(event: dict) -> int:
```

- [ ] **Step 2: Rewrite swee/palfeed.py**

Change the import block (line 9) from:

```python
from swee.palfeed_notability import ACQUISITION_LABELS, notability_tier, talent_score
```

to:

```python
from swee.palfeed_notability import notability_tier, talent_score
```

Add these two constants after `PALFEED_BATCH_LIMIT = 5` (line 15), before `last_event_id`:

```python
ACQUISITION_VERBS = {
    "wild_capture": "caught",
    "hatched": "hatched",
    "purchased": "purchased",
}

TIER_ARTICLES = {
    "Lucky": "a",
    "Awakened": "an",
    "Perfect": "a",
    "Excellent": "an",
    "Great": "a",
}
```

Change `format_catch_embed` (currently lines 47-56) from:

```python
def format_catch_embed(event, tier):
    title = f"{event.get('character_id') or 'Unknown Pal'} — {tier}"
    acquisition = ACQUISITION_LABELS.get(event.get("acquisition_type"), "Acquired")
    level = event.get("level")
    description = acquisition + (f" — Level {level}" if level is not None else "")
    fields = [("Talent Score", f"{talent_score(event)}/300")]
    owner_name = resolve_owner_name(event.get("owner_player_uid"))
    if owner_name:
        fields.append(("Owner", owner_name))
    return title, description, fields
```

to:

```python
def format_catch_embed(event, tier):
    character_id = event.get("character_id") or "Unknown Pal"
    verb = ACQUISITION_VERBS.get(event.get("acquisition_type"), "acquired")
    article = TIER_ARTICLES.get(tier, "a")
    owner_name = resolve_owner_name(event.get("owner_player_uid"))
    if owner_name:
        title = f"{owner_name} {verb} {article} {tier} {character_id}"
    else:
        title = f"{article.capitalize()} {tier} {character_id} was {verb}"

    level = event.get("level")
    level_prefix = f"Level {level} · " if level is not None else ""
    hp = event.get("talent_hp", 0)
    attack = event.get("talent_shot", 0)
    defense = event.get("talent_defense", 0)
    total = talent_score(event)
    description = f"{level_prefix}{hp} HP / {attack} Attack / {defense} Defense — {total}/300 IVs"

    return title, description
```

Change `palfeed_ticker`'s loop body (currently lines 67-77) from:

```python
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
```

to:

```python
    for event in events:
        tier = notability_tier(event)
        if tier:
            title, description = format_catch_embed(event, tier)
            sent = await broadcast_embed(
                title, description, COLOR_PALFEED, channel_id=PALFEED_CHANNEL_ID,
            )
            if not sent:
                log.warning("palfeed announcement failed for event %s, will retry next tick", event["id"])
                break
        save_last_event_id(event["id"])
```

- [ ] **Step 3: Manually verify the five approved example cases**

`format_catch_embed` needs `swee.config` (via `swee.embeds`/`swee.player_history`) to import, which requires a populated `.env` — same constraint the rest of `swee/palfeed.py` already has. Verify with a one-off script (not committed) that stubs the required env vars, monkeypatches `resolve_owner_name` for the two owner-known cases, and asserts every title/description against the exact five examples approved in `docs/superpowers/specs/2026-07-20-palfeed-embed-copy-design.md`:

Run this from the repo root:

```bash
python3 - <<'PYEOF'
import os
os.environ.setdefault("DISCORD_BOT_TOKEN", "x")
os.environ.setdefault("GUILD_ID", "1")
os.environ.setdefault("ADMIN_ROLE_ID", "1")
os.environ.setdefault("RELAY_CHANNEL_ID", "1")
os.environ.setdefault("STATS_CHANNEL_ID", "1")
os.environ.setdefault("ACTIVITY_CHANNEL_ID", "1")
os.environ.setdefault("ALERTS_CHANNEL_ID", "1")
os.environ.setdefault("ADMIN_CHANNEL_ID", "1")
os.environ.setdefault("COMMANDS_CHANNEL_ID", "1")
os.environ.setdefault("BOT_UPDATES_CHANNEL_ID", "1")
os.environ.setdefault("REST_HOST", "x")
os.environ.setdefault("REST_PORT", "1")
os.environ.setdefault("REST_USER", "x")
os.environ.setdefault("REST_PASSWORD", "x")
os.environ.setdefault("PALWORLD_SETTINGS_INI_PATH", "/tmp/x")
os.environ.setdefault("PALWORLD_INSTALL_DIR", "/tmp")

import swee.palfeed as palfeed

def fake_resolve(uid):
    return {"kippei-uid": "Kippei", "yeni-uid": "Yeni"}.get(uid)

palfeed.resolve_owner_name = fake_resolve

cases = [
    (
        {"character_id": "Foxparks", "level": 12, "talent_hp": 60, "talent_shot": 50,
         "talent_defense": 70, "acquisition_type": "wild_capture", "owner_player_uid": "kippei-uid"},
        "Lucky",
        "Kippei caught a Lucky Foxparks",
        "Level 12 · 60 HP / 50 Attack / 70 Defense — 180/300 IVs",
    ),
    (
        {"character_id": "Direhowl", "level": 8, "talent_hp": 40, "talent_shot": 60,
         "talent_defense": 40, "acquisition_type": "purchased", "owner_player_uid": "yeni-uid"},
        "Awakened",
        "Yeni purchased an Awakened Direhowl",
        "Level 8 · 40 HP / 60 Attack / 40 Defense — 140/300 IVs",
    ),
    (
        {"character_id": "Quivern", "level": 20, "talent_hp": 100, "talent_shot": 100,
         "talent_defense": 100, "acquisition_type": "wild_capture", "owner_player_uid": "unknown-uid"},
        "Perfect",
        "A Perfect Quivern was caught",
        "Level 20 · 100 HP / 100 Attack / 100 Defense — 300/300 IVs",
    ),
    (
        {"character_id": "Broncherry", "level": None, "talent_hp": 95, "talent_shot": 95,
         "talent_defense": 95, "acquisition_type": "hatched", "owner_player_uid": "kippei-uid"},
        "Excellent",
        "Kippei hatched an Excellent Broncherry",
        "95 HP / 95 Attack / 95 Defense — 285/300 IVs",
    ),
    (
        {"character_id": "Direhowl", "level": 5, "talent_hp": 85, "talent_shot": 85,
         "talent_defense": 85, "acquisition_type": "wild_capture", "owner_player_uid": "yeni-uid"},
        "Great",
        "Yeni caught a Great Direhowl",
        "Level 5 · 85 HP / 85 Attack / 85 Defense — 255/300 IVs",
    ),
]

for event, tier, expected_title, expected_description in cases:
    title, description = palfeed.format_catch_embed(event, tier)
    assert title == expected_title, f"title mismatch: {title!r} != {expected_title!r}"
    assert description == expected_description, f"description mismatch: {description!r} != {expected_description!r}"

print("all 5 cases match")
PYEOF
```

Expected output: `all 5 cases match`, no `AssertionError`.

- [ ] **Step 4: Run the full test suite (regression check)**

Run: `python -m unittest discover tests -v`
Expected: `OK` (80 tests, unchanged — this task touches no tested module).

- [ ] **Step 5: Commit**

```bash
git add swee/palfeed.py swee/palfeed_notability.py
git commit -m "feat: personalize palfeed catch embed copy"
```

---

## Self-Review

**Spec coverage:** owner-known/unresolved title forms ✓ (Step 2); verb-by-acquisition-type and article-by-tier lookups ✓ (Step 2); description with talent breakdown + total + conditional level prefix ✓ (Step 2); 2-tuple return + `broadcast_embed` call updated ✓ (Step 2); `ACQUISITION_LABELS` removed from `palfeed_notability.py` ✓ (Step 1); no new test file, manual verification instead ✓ (Step 3).

**Placeholder scan:** none — every step has complete code or a fully concrete verification script.

**Type consistency:** `format_catch_embed(event, tier) -> (title, description)` (Step 2) matches the unpacking (`title, description = format_catch_embed(...)`) in `palfeed_ticker`, same step. `ACQUISITION_VERBS`/`TIER_ARTICLES` (defined Step 2) are used only within the same file, no cross-task naming risk.
