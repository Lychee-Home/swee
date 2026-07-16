# Migrate release versioning to release-please — design

## Problem

`.github/workflows/ci.yml` currently deploys *and* releases on every push to `main`: the `deploy`
job restarts the live bot immediately, and the `release` job (via
`scripts/compute-version-bump.sh`) tags and publishes a GitHub Release in the same run, if the
commit's Conventional Commit type warrants a bump (see
[`2026-07-10-release-versioning-design.md`](2026-07-10-release-versioning-design.md)). There's no
way to merge work to `main` without it going live and being released in the same instant — every
PR merge is effectively a ship decision. This replaces that with a gated flow: merging to `main`
no longer deploys or releases anything by itself; both happen only when a maintained "Release PR"
is deliberately merged, whenever ready to ship.

## Scope

- Adopt `googleapis/release-please-action` (release type `simple`, since this repo has no
  `pyproject.toml`/`setup.py` version field to bump) in place of
  `scripts/compute-version-bump.sh` and the manual tag/`gh release create` step.
- `release-please-config.json` and `.release-please-manifest.json`, seeded at the current version
  (`2.4.0`, matching the existing `v2.4.0` tag) so the first Release PR computes its bump from
  there, not from zero.
- `CHANGELOG.md` maintained automatically as part of each Release PR (release-please's default
  behavior), in addition to GitHub Release notes.
- Restructure `.github/workflows/ci.yml` so both `deploy` and tag/release creation are gated on
  the same signal: release-please's `release_created` output, which is only true on the run where
  its own Release PR gets merged.
- Delete `scripts/compute-version-bump.sh` and `scripts/test-compute-version-bump.sh` — no
  replacement test suite is needed since release-please's commit parsing is the project's own
  tested code, not ours to unit test.

Out of scope:
- No change to commit type → bump level semantics (`feat` → minor, `fix`/`perf` → patch,
  `!`/`BREAKING CHANGE:` → major) — release-please's defaults already match the existing scheme.
- No change to `deploy/ci-deploy.sh` or the deploy mechanics themselves — only *when* the deploy
  job runs changes, not what it does.
- No update to the release-announcements bot feature's `humanize_release_notes` regex (see
  Interaction with release announcements below) — flagged as a risk, not fixed here.
- No branch protection changes.

## Workflow structure

`.github/workflows/ci.yml`, `on: push: branches: [main]` (the existing `paths` filter is dropped —
see Removing the paths filter below):

1. **`release-please` job** (`ubuntu-latest`) — runs `googleapis/release-please-action` on every
   push to `main`. On an ordinary feature-PR merge, it just opens/updates the standing Release PR
   with the accumulated version bump and changelog entries, and outputs `release_created: false`.
   When *that* Release PR is merged, this same job instead tags the release, creates the GitHub
   Release, and outputs `release_created: true` (plus `tag_name`).
2. **`deploy` job** — unchanged internally, but now `needs: release-please` and
   `if: needs.release-please.outputs.release_created == 'true'`. Only fires on the run where a
   release was actually cut, i.e. only when the Release PR was the thing just merged.

This means an ordinary PR merging to `main` does nothing but update the Release PR's diff — no
deploy, no tag, no release. Merging the Release PR is the only action that ships.

## Removing the paths filter

The current trigger only runs on changes to `main.py`/`swee/**`/`requirements.txt`, so that
docs-only or chore-only commits wouldn't trigger a pointless deploy. Under the new gating, that
job is redundant: release-please only produces `release_created: true` when there's an actual
version bump to release (a `docs:`/`chore:`-only commit never bumps the version), so `deploy`
already won't fire for those changes. The `paths` filter is removed so release-please still sees
every commit for accurate changelog bookkeeping, even ones that don't touch app code.

## Interaction with release announcements

The existing `release_ticker` feature (see
[`2026-07-10-release-announcements-design.md`](2026-07-10-release-announcements-design.md)) parses
GitHub's auto-generated `## What's Changed` / `* type: desc by @user in #N` release body format
via `humanize_release_notes`. Release-please's generated release notes use its own Conventional
Commits changelog format (`### Features` / `### Bug Fixes` sections with markdown bullets), which
won't match that regex. `humanize_release_notes` already falls back to posting the raw release
body when it finds zero recognized lines, so announcements keep working but will look less
polished (raw release-please changelog text) until the humanizer is updated separately. Not fixing
this now — flagged as a follow-up.

## Bootstrap

Seed `.release-please-manifest.json` with `{".": "2.4.0"}` so the first Release PR release-please
opens computes its bump from the current `v2.4.0` tag, matching what's actually deployed today.

## Non-goals / risks accepted

- Release announcements will temporarily degrade to raw (less readable) release-please changelog
  text until `humanize_release_notes` is updated for the new format — acceptable since it degrades
  gracefully rather than breaking (see Interaction with release announcements above).
- Deploys are now deliberate rather than immediate — a merged feature PR sits un-deployed until
  someone merges the Release PR. This is the entire point of the change, but worth naming: if a
  release is forgotten, fixes/features sit live-in-`main`-but-not-live-in-production indefinitely.
- release-please's own commits (Release PR updates, the `chore(main): release X.Y.Z` merge
  commit) land on `main` like any other commit and will show up in `git log`; no special handling
  needed since nothing currently depends on `main`'s commit history being release-workflow-free.
