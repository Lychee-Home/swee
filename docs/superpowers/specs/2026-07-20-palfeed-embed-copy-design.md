# palfeed embed copy — personalized catch narrative

## Summary

Rewrite `swee/palfeed.py`'s `format_catch_embed` to read as a personalized highlight-feed post
("Kippei caught a Lucky Foxparks") instead of a data dump (title `"<character_id> — <tier>"` plus
separate `Talent Score`/`Owner` fields). This replaces the embed shape shipped in
`2026-07-20-palfeed-design.md`/`2026-07-20-palfeed-owner-name-design.md` — no other part of those
specs changes.

## Design

**Title**, owner known (the expected case now that owner resolution — see
`2026-07-20-palfeed-owner-name-design.md` — is live):

```
"{owner} {verb} a{n} {tier} {character_id}"
```

e.g. `"Kippei caught a Lucky Foxparks"`, `"Yeni purchased an Awakened Direhowl"`.

**Title**, owner unresolved (rare — a catch by a player `resolve_owner_name` has never seen):

```
"A{n} {tier} {character_id} was {verb}"
```

e.g. `"A Perfect Quivern was caught"`.

`verb` by `acquisition_type`: `wild_capture` → `"caught"`, `hatched` → `"hatched"`, `purchased` →
`"purchased"` (also used as the passive form in the fallback title — all three already work
unchanged as past participles, no separate passive-verb table needed).

`a`/`an` is a fixed per-tier lookup (only 5 tier strings exist, and the tier word is what
immediately follows the article, not the species name), not a general vowel-detection rule:
`Lucky`→"a", `Awakened`→"an", `Perfect`→"a", `Excellent`→"an", `Great`→"a".

**Description** — talent breakdown + total, level folded in when present:

```
"Level {level} · {talent_hp} HP / {talent_shot} Attack / {talent_defense} Defense — {total}/300 IVs"
```

For hatched pals (`level` is `None`), the `"Level {level} · "` prefix is dropped entirely — same
omission pattern the current implementation already uses.

Display copy only: "IVs" and "Attack" are swee-side labels. The underlying data keeps its existing
names (`talent_hp`/`talent_shot`/`talent_defense`, `level`, `acquisition_type`) — those come from
`palsave-api`'s event JSON, which mirrors the save file's own field names (`Talent_HP`/
`Talent_Shot`/`Talent_Defense`), and this change doesn't touch that contract.

**No more separate embed fields.** `Owner` and `Talent Score` both move into title/description, so
`broadcast_embed` is called with `fields=None` (or omitted) — title + description + color only.

## Architecture

Single-function change: `swee/palfeed.py`'s `format_catch_embed(event, tier)` is rewritten to
return `(title, description)` instead of `(title, description, fields)`, and `palfeed_ticker`'s
`broadcast_embed(...)` call drops the `fields=fields` argument. `ACQUISITION_LABELS` (currently
full phrases like `"Caught in the wild"`, defined in `swee/palfeed_notability.py`) is replaced by
a verb-only mapping, since the acquisition type is now expressed as the title's verb rather than a
standalone description phrase.

`resolve_owner_name` (from `swee/player_history.py`, already implemented) is still the lookup used
to get `owner`; nothing about that function changes.

## Testing

No new pure-function surface worth a dedicated test beyond what already exists — `format_catch_embed`
itself has never been unit tested (it needs a populated `.env` to import via `swee.config`, same as
the rest of `swee/palfeed.py`, per existing precedent). The tier→article mapping and
acquisition_type→verb mapping are small enough constant lookups that they don't warrant a separate
pure module the way `notability_tier`/`talent_score` did — they're presentation constants specific
to this one function, not logic reused elsewhere.

## Out of scope

- No change to `resolve_owner_name`, `notability_tier`, `talent_score`, or any data-layer code —
  this is purely `format_catch_embed`'s output shape.
- No change to `palsave-api`'s event JSON field names.
