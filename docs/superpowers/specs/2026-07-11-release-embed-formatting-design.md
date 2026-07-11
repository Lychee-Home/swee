# Release-announcement embed formatting — design

## Problem

The `#bot-updates` release-announcement embed (`release_ticker` in `main.py`) uses emoji in its
title and section headers ("🎉 vX.Y.Z released", "🆕 New", "🛠️ Fixes"). The user wants the emoji
removed and the section headers given clearer visual weight now that the emoji cue is gone.

## Change

Three edits, all in `main.py`:

1. **Title** (`release_ticker`, currently `f"\U0001f389 {tag} released"`): drop the emoji →
   `f"{tag} released"`. Discord renders embed titles bold at a fixed size already larger than the
   body — there's no markdown that makes it larger still, so this is emoji removal only, no other
   title styling change.

2. **Section labels** (`RELEASE_NOTE_LABELS`, currently
   `{"feat": "🆕 New", "fix": "🛠️ Fixes", "perf": "🛠️ Fixes"}`): drop the emoji prefixes →
   `{"feat": "New", "fix": "Fixes", "perf": "Fixes"}`.

3. **Section header styling** (`humanize_release_notes`, currently builds each section as
   `f"{label}\n{lines}"`): bold the header → `f"**{label}**\n{lines}"`, so the plain-text labels
   from (2) still stand out from the bullet list beneath them.

`RELEASE_NOTE_SECTION_ORDER` (`tuple(dict.fromkeys(RELEASE_NOTE_LABELS.values()))`) needs no
change — it derives its order from `RELEASE_NOTE_LABELS`'s values automatically, whatever they are.

Bullet formatting (`• {desc}`) is unchanged — not flagged as a problem.

## Out of scope

- No change to embed color, timestamp, or any other embed field.
- No change to how release notes are fetched or parsed (`fetch_latest_release`, `RELEASE_NOTE_RE`).

## Testing

No test suite exists in this repo. Verification: manually call `humanize_release_notes` with a
sample release body containing both `feat:` and `fix:` lines and confirm the output has no emoji
and bold headers.
