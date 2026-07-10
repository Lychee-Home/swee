# Release versioning — design

## Problem

Pushes to `main` already auto-deploy (`.github/workflows/deploy.yml` on the self-hosted
runner), so there's no gate to add a version to. What's missing is a way to know *what's
running* and *what changed* between deploys: no git tags exist yet, there's no changelog, and
there's no way to reference "the version where X broke" when reporting or debugging an issue.
This adds semantic version tags and GitHub Releases, generated automatically from merged PR
titles, without touching the deploy path itself.

## Scope

- Semantic versioning (`vMAJOR.MINOR.PATCH`), bootstrapped at `v1.0.0` on current `main` (it's
  already live in production, not pre-release software).
- A new GitHub Actions workflow that tags and releases automatically on push to `main`, driven
  by Conventional Commits type parsed from the squash-merge commit message (= PR title).
- Only `feat`/`fix`/`perf` (or anything marked breaking) produce a release; `docs`/`chore`/
  `ci`/`style`/`test`/`refactor`/`build`/`revert` merge without bumping the version.
- A PR title lint check (advisory, not blocking — see Non-goals) so a malformed title is caught
  before merge instead of silently producing no release or a miscategorized one.
- A repo settings change: squash merge becomes the only allowed merge method, since the release
  workflow reads the single squash commit on `main` as the source of truth for each PR.

Out of scope:
- No `CHANGELOG.md` file to hand-maintain — `gh release create --generate-notes` produces
  per-release notes from merged PRs, which is enough.
- No change to `main.py` — the bot doesn't need to know or report its own version (confirmed:
  git tag + GitHub Release is sufficient; nothing surfaces in `/status` or logs).
- No branch protection rule enforcing the PR title check — see Non-goals.
- No change to `deploy.yml` or the deploy path — tagging happens independently of, and after,
  the deploy that already occurred on push.

## Versioning scheme

Conventional Commit type on the PR title (= squash-merge commit subject) maps to bump level:

| Signal | Bump |
|---|---|
| `!` after type/scope, or `BREAKING CHANGE:` in commit body | MAJOR |
| `feat:` | MINOR |
| `fix:` / `perf:` | PATCH |
| anything else (`docs:`, `chore:`, `ci:`, `style:`, `test:`, `refactor:`, `build:`, `revert:`) | no release |

MAJOR is reserved for changes that break an existing deployment on upgrade — e.g. a new
required `.env` var, a removed/renamed slash command, changed REST config shape.

## Repo settings change

Squash merge becomes the only allowed merge method (currently merge/rebase/squash are all
enabled). This guarantees exactly one commit lands on `main` per PR, titled with the PR title,
which is what the release workflow parses. Applied via `gh api` against
`PATCH /repos/{owner}/{repo}` (`squash_merge_commit_title: PR_TITLE`, merge/rebase disabled).

## PR title lint (`.github/workflows/pr-title-lint.yml`)

Runs on `pull_request` (`opened`, `edited`, `synchronize`), using
`amannn/action-semantic-pull-request` to validate the title matches
`type(scope)!?: subject` with `type` in `feat|fix|perf|refactor|docs|chore|style|test|ci|build|revert`.
Reports a check on the PR (pass/fail visible in the PR checks list).

## Release workflow (`.github/workflows/release.yml`)

Triggers on `push` to `main`, runs on a GitHub-hosted runner (`ubuntu-latest`) — it only
touches git tags and GitHub Releases, not the deploy host, so it doesn't need the self-hosted
runner.

1. `actions/checkout` with `fetch-depth: 0` (need full tag history) and `fetch-tags: true`.
2. Read `HEAD`'s commit subject and body (`git log -1 --format=%s` / `%b`).
3. Parse Conventional Commit type + breaking marker with a regex:
   `^(?<type>\w+)(\(.+\))?(?<breaking>!)?: `. If `type` isn't `feat`/`fix`/`perf` and there's no
   `!` and no `BREAKING CHANGE:` in the body → exit 0, no release.
4. Otherwise determine bump level (breaking → MAJOR, `feat` → MINOR, `fix`/`perf` → PATCH) and
   apply it to the latest existing tag (`git describe --tags --abbrev=0 --match 'v*'`).
5. Create an annotated tag for the new version and `git push origin <tag>`.
6. `gh release create <tag> --generate-notes` — GitHub auto-generates release notes from PRs
   merged since the previous tag.

If step 3 finds no valid Conventional Commit prefix at all (title lint didn't catch it, e.g. an
admin merge bypassing checks), it's treated the same as a non-bumping type: no release, no
error. This fails safe (no version drift from a malformed title) at the cost of silently
skipping a release that should have happened — acceptable since it's easy to notice (no new
tag appears) and fix with a manual tag.

## Bootstrap (one-time, part of this implementation, not the workflow)

Tag current `main` HEAD as `v1.0.0` and create the corresponding GitHub Release manually, so
the release workflow always has a prior tag to compute bumps from. Without this the first
`git describe --tags` in the workflow would fail with no tags to describe from.

## Non-goals / risks accepted

- The PR title check is advisory only, not enforced via branch protection — `main` currently
  has no branch protection rule at all (confirmed via `gh api .../branches/main/protection` →
  404), and adding one is a broader repo-settings change than this task's scope. A malformed
  title merges fine; it just doesn't produce a release (see step 3's fail-safe behavior above).
  Revisit if malformed titles become a recurring problem.
- No automation enforces "squash merge only" beyond the repo setting itself — if merge/rebase
  are manually re-enabled later, the release workflow's single-commit assumption breaks
  silently (it'll parse whatever commit landed as HEAD, which may not be the PR title).
- No retroactive tags for the 5 PRs merged before this change — history starts clean at
  `v1.0.0`.
