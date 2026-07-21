"""Pure notability-scoring functions for the pal-catch recap feed. Zero
swee-internal imports on purpose — this must stay importable without a
populated .env, the same guarantee swee/palworld_settings.py provides.

Talent score (talent_hp + talent_shot + talent_defense, max 300) tiers are
calibrated against one reference save's own distribution, not a verified
community standard — see palsave-api's project memory
(recap_notability_rules.md) for how these were derived. Structural facts
about an event (acquisition_type classification, recruitable-NPC exclusion,
etc.) are palsave-api's responsibility; this module only decides what's
worth posting to a Discord highlight channel.
"""

TALENT_TIERS = (
    (300, "Perfect"),
    (280, "Excellent"),
)


def talent_score(event: dict) -> int:
    return event.get("talent_hp", 0) + event.get("talent_shot", 0) + event.get("talent_defense", 0)


def notability_tier(event: dict) -> str:
    if event.get("is_rare_pal"):
        return "Lucky"
    if event.get("is_awakening"):
        return "Awakened"
    score = talent_score(event)
    for threshold, label in TALENT_TIERS:
        if score >= threshold:
            return label
    return ""
