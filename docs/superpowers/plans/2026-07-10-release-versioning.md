# Release Versioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically tag and release semantic versions on `main` whenever a merged PR
changes bot behavior, driven by the PR's Conventional Commit title.

**Architecture:** A pure-bash script (`scripts/compute-version-bump.sh`) contains the
version-bump logic and is unit-tested directly with a plain-bash test harness (no new test
framework). A `release.yml` GitHub Actions workflow calls that script on every push to `main`
and, when it reports a bump, tags and creates a GitHub Release. A separate `pr-title-lint.yml`
workflow gives PR authors fast feedback if their title doesn't parse. Two one-time operational
steps (bootstrap tag, squash-merge-only repo setting) sit outside the workflow files themselves.

**Tech Stack:** Bash (workflow scripts), GitHub Actions, `gh` CLI, `amannn/action-semantic-pull-request` (marketplace action for PR title lint).

## Global Constraints

- Semantic versioning, `vMAJOR.MINOR.PATCH`, bootstrapped at `v1.0.0` (spec: Versioning scheme).
- Only `feat`/`fix`/`perf`, or anything marked breaking (`!` or `BREAKING CHANGE:` footer),
  produce a release; `docs`/`chore`/`ci`/`style`/`test`/`refactor`/`build`/`revert` merge
  without a version bump (spec: Scope, Versioning scheme).
- Squash merge is the only allowed merge method on this repo going forward — the release
  workflow reads the single squash commit on `main` as its source of truth (spec: Repo settings
  change).
- PR title check is advisory only — no branch protection rule is added in this plan (spec:
  Non-goals).
- No `CHANGELOG.md` to maintain — `gh release create --generate-notes` covers it (spec: Scope).
- No changes to `main.py` or `deploy.yml` — this is fully independent of the bot and the deploy
  path (spec: Scope).
- A malformed/missing Conventional Commit prefix on `main`'s HEAD commit must fail safe: no
  release, no workflow error (spec: Release workflow, step 3).

---

### Task 1: Version-bump script with tests

**Files:**
- Create: `scripts/compute-version-bump.sh`
- Create: `scripts/test-compute-version-bump.sh`

**Interfaces:**
- Consumes: nothing (pure function of env vars).
- Produces: `compute-version-bump.sh` — reads `COMMIT_SUBJECT`, `COMMIT_BODY` (optional,
  default empty), `LATEST_TAG` (optional, default `v0.0.0`) from the environment; writes to
  stdout either just `level=none` or two lines `level=<major|minor|patch>` followed by
  `tag=vX.Y.Z`. Always exits 0. This is the exact contract Task 2's workflow relies on.

- [ ] **Step 1: Write the test harness (it will fail — the script doesn't exist yet)**

Create `scripts/test-compute-version-bump.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$script_dir/compute-version-bump.sh"
failures=0

run_case() {
  local name="$1" subject="$2" body="$3" latest_tag="$4" expected="$5"
  local actual
  actual="$(COMMIT_SUBJECT="$subject" COMMIT_BODY="$body" LATEST_TAG="$latest_tag" bash "$script")"
  if [[ "$actual" == "$expected" ]]; then
    echo "PASS: $name"
  else
    echo "FAIL: $name"
    echo "  expected: $expected"
    echo "  actual:   $actual"
    failures=$((failures + 1))
  fi
}

run_case "feat bumps minor" \
  "feat: add /uptime command" "" "v1.2.3" \
  $'level=minor\ntag=v1.3.0'

run_case "fix bumps patch" \
  "fix: correct RAM percentage calc" "" "v1.2.3" \
  $'level=patch\ntag=v1.2.4'

run_case "perf bumps patch" \
  "perf: reduce log tailer polling interval" "" "v1.2.3" \
  $'level=patch\ntag=v1.2.4'

run_case "breaking bang bumps major" \
  "feat!: require RELAY_CHANNEL_ID" "" "v1.2.3" \
  $'level=major\ntag=v2.0.0'

run_case "BREAKING CHANGE footer bumps major" \
  "fix: change REST auth header" "BREAKING CHANGE: renamed REST_PASSWORD to REST_TOKEN" "v1.2.3" \
  $'level=major\ntag=v2.0.0'

run_case "docs produces no release" \
  "docs: fix typo in README" "" "v1.2.3" \
  "level=none"

run_case "chore produces no release" \
  "chore: bump discord.py pin" "" "v1.2.3" \
  "level=none"

run_case "unrecognized prefix produces no release" \
  "wip: experiment" "" "v1.2.3" \
  "level=none"

run_case "no prefix at all produces no release" \
  "Merge branch 'main' into feature" "" "v1.2.3" \
  "level=none"

run_case "scoped feat bumps minor" \
  "feat(alerts): add cause detector for kernel OOM" "" "v1.2.3" \
  $'level=minor\ntag=v1.3.0'

if [[ "$failures" -gt 0 ]]; then
  echo "$failures test(s) failed"
  exit 1
fi

echo "All tests passed"
```

- [ ] **Step 2: Run the test harness to verify it fails**

Run: `bash scripts/test-compute-version-bump.sh`
Expected: fails immediately — `scripts/compute-version-bump.sh: No such file or directory` (or
similar), since the script under test doesn't exist yet.

- [ ] **Step 3: Write the implementation**

Create `scripts/compute-version-bump.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

types='feat|fix|perf|refactor|docs|chore|style|test|ci|build|revert'
pattern="^(${types})(\([^)]*\))?(!)?: "

subject="${COMMIT_SUBJECT:-}"
body="${COMMIT_BODY:-}"
latest_tag="${LATEST_TAG:-v0.0.0}"

if [[ "$subject" =~ $pattern ]]; then
  type="${BASH_REMATCH[1]}"
  breaking_marker="${BASH_REMATCH[3]}"
else
  echo "level=none"
  exit 0
fi

if [[ -n "$breaking_marker" || "$body" == *"BREAKING CHANGE:"* ]]; then
  level="major"
elif [[ "$type" == "feat" ]]; then
  level="minor"
elif [[ "$type" == "fix" || "$type" == "perf" ]]; then
  level="patch"
else
  level="none"
fi

echo "level=$level"

if [[ "$level" == "none" ]]; then
  exit 0
fi

version="${latest_tag#v}"
IFS='.' read -r major minor patch <<< "$version"

case "$level" in
  major) major=$((major + 1)); minor=0; patch=0 ;;
  minor) minor=$((minor + 1)); patch=0 ;;
  patch) patch=$((patch + 1)) ;;
esac

echo "tag=v${major}.${minor}.${patch}"
```

- [ ] **Step 4: Run the test harness to verify it passes**

Run: `bash scripts/test-compute-version-bump.sh`
Expected: every case prints `PASS: ...` and the last line is `All tests passed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/compute-version-bump.sh scripts/test-compute-version-bump.sh
git commit -m "feat: add version-bump computation script with tests"
```

---

### Task 2: Release workflow

**Files:**
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: `scripts/compute-version-bump.sh` from Task 1 — invoked as
  `COMMIT_SUBJECT="$subject" COMMIT_BODY="$body" LATEST_TAG="$latest_tag" bash scripts/compute-version-bump.sh`,
  output lines captured into `$GITHUB_OUTPUT`.
- Produces: on push to `main`, either no-ops (script reports `level=none`) or creates+pushes an
  annotated tag `vX.Y.Z` and a GitHub Release with auto-generated notes.

- [ ] **Step 1: Write the workflow file**

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    branches: [main]

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          fetch-tags: true

      - name: Determine release
        id: release
        run: |
          latest_tag="$(git describe --tags --abbrev=0 --match 'v*')"
          subject="$(git log -1 --format=%s)"
          body="$(git log -1 --format=%b)"
          COMMIT_SUBJECT="$subject" COMMIT_BODY="$body" LATEST_TAG="$latest_tag" \
            bash scripts/compute-version-bump.sh >> "$GITHUB_OUTPUT"

      - name: Create tag and release
        if: steps.release.outputs.level != 'none'
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          tag="${{ steps.release.outputs.tag }}"
          git tag -a "$tag" -m "$tag"
          git push origin "$tag"
          gh release create "$tag" --generate-notes
```

- [ ] **Step 2: Verify the YAML is well-formed and the script is referenced correctly**

Run: `grep -n "compute-version-bump.sh" .github/workflows/release.yml`
Expected: one match, on the `bash scripts/compute-version-bump.sh` line — confirms the workflow
calls the Task 1 script with the exact same interface the tests validated.

This workflow can't be fully exercised until it's on `main` and receives a push (Task 6 covers
end-to-end verification after merge).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "feat: add automated release tagging on push to main"
```

---

### Task 3: PR title lint workflow

**Files:**
- Create: `.github/workflows/pr-title-lint.yml`

**Interfaces:**
- Consumes: nothing from earlier tasks — standalone workflow.
- Produces: a PR check ("Semantic Pull Request") that passes/fails based on whether the PR
  title matches `type(scope)!?: subject` with `type` in the same list Task 1's script accepts
  (`feat|fix|perf|refactor|docs|chore|style|test|ci|build|revert`).

- [ ] **Step 1: Write the workflow file**

Create `.github/workflows/pr-title-lint.yml`:

```yaml
name: PR Title Lint

on:
  pull_request:
    types: [opened, edited, synchronize, reopened]

permissions:
  pull-requests: read
  statuses: write

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: amannn/action-semantic-pull-request@v5
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          types: |
            feat
            fix
            perf
            refactor
            docs
            chore
            style
            test
            ci
            build
            revert
```

- [ ] **Step 2: Verify the type list matches Task 1's script exactly**

Run: `grep -oE "feat\|fix\|perf\|refactor\|docs\|chore\|style\|test\|ci\|build\|revert" scripts/compute-version-bump.sh`

Then compare by eye against the `with.types` list above — both must contain exactly these 11
types, in the same set (order doesn't matter). This keeps the advisory check and the actual
release logic from silently drifting apart.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/pr-title-lint.yml
git commit -m "ci: add PR title lint for conventional commit format"
```

---

### Task 4: README documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: a new "Versioning" section a future reader can find without reading workflow YAML.

- [ ] **Step 1: Add a Versioning section to README.md**

Insert a new section after the existing "### Continuous deployment" subsection (end of the
"## Deployment" section), before "## Requirements":

```markdown
### Versioning

Releases are tagged automatically. Every PR title must follow [Conventional
Commits](https://www.conventionalcommits.org/) format (`feat: ...`, `fix: ...`, `chore: ...`,
etc. — enforced by a PR check, though not merge-blocking). Squash merge is the only allowed
merge method, so each PR becomes exactly one commit on `main` titled with its PR title.

On push to `main`, `.github/workflows/release.yml` reads that commit's type:
- `feat` bumps MINOR, `fix`/`perf` bump PATCH, and a `!` after the type/scope (or a
  `BREAKING CHANGE:` footer) bumps MAJOR — each creates a new `vX.Y.Z` tag and GitHub Release
  with auto-generated notes.
- Any other type (`docs`, `chore`, `ci`, `style`, `test`, `refactor`, `build`, `revert`) merges
  without a release.

Reserve `!`/`BREAKING CHANGE:` for changes that break an existing deployment on upgrade — e.g. a
new required `.env` var, a removed/renamed slash command, a changed REST config shape.
```

- [ ] **Step 2: Verify placement**

Run: `grep -n "^## \|^### " README.md`
Expected: `### Versioning` appears directly after `### Continuous deployment` and before
`## Requirements`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document the release versioning workflow"
```

---

### Task 5: Bootstrap `v1.0.0` and restrict merge methods

These are one-time operational steps against the live GitHub repo, not file changes — do them
right before merging the PR from Tasks 1-4, and confirm with the user before running each
(they affect shared repo state: a public tag/release and a merge-method restriction).

**Files:** none.

**Interfaces:** none — these don't produce anything later tasks read from.

- [ ] **Step 1: Tag current `main` HEAD as `v1.0.0` and create the release**

Confirm with the user first (creates a public tag and GitHub Release on `main`). Then, with
`main` checked out and up to date:

```bash
git checkout main
git pull --ff-only origin main
git tag -a v1.0.0 -m "v1.0.0"
git push origin v1.0.0
gh release create v1.0.0 --notes "Initial tagged release. First version-tracked release of swee; no prior tags existed."
```

Expected: `gh release create` prints the release URL; `git tag -l` locally now includes
`v1.0.0`. This is what step 1 of the release workflow (Task 2) will `git describe` against on
the very next feature push.

- [ ] **Step 2: Restrict the repo to squash-merge only**

Confirm with the user first (changes repo settings). Then:

```bash
gh api -X PATCH repos/byroncustodio/swee \
  -f squash_merge_commit_title=PR_TITLE \
  -F allow_squash_merge=true \
  -F allow_merge_commit=false \
  -F allow_rebase_merge=false
```

Expected: the API call returns the updated repo object with `"allow_merge_commit": false`,
`"allow_rebase_merge": false`, `"allow_squash_merge": true`.

- [ ] **Step 3: Verify the setting took effect**

Run: `gh api repos/byroncustodio/swee --jq '{squash: .allow_squash_merge, merge: .allow_merge_commit, rebase: .allow_rebase_merge}'`
Expected: `{"squash":true,"merge":false,"rebase":false}`

---

### Task 6: Open the PR and verify end-to-end

**Files:** none — this bundles the branch from Tasks 1-4 into one PR (per project convention:
spec/plan/code land together, not as separate PRs).

**Interfaces:** none.

- [ ] **Step 1: Push the branch**

```bash
git push -u origin docs/release-versioning-design
```

- [ ] **Step 2: Open the PR with a Conventional Commit title**

The PR title becomes the squash-merge commit subject, which the release workflow will parse —
title it as a `feat` so merging it produces the first automated release, `v1.1.0`:

```bash
gh pr create --title "feat: add automated semantic-version release tagging" --body "$(cat <<'EOF'
## Summary
- Design spec + implementation plan for automated release tagging (docs/superpowers/specs, docs/superpowers/plans).
- scripts/compute-version-bump.sh + bash test harness — pure version-bump logic, unit tested.
- .github/workflows/release.yml — tags + creates a GitHub Release on push to main when the commit is feat/fix/perf/breaking.
- .github/workflows/pr-title-lint.yml — advisory Conventional Commit title check on PRs.
- README.md — documents the versioning workflow.

Repo settings changed separately (not in this diff): squash-merge-only, and v1.0.0 bootstrap tag already pushed to main.

## Test plan
- [x] `bash scripts/test-compute-version-bump.sh` — all cases pass
- [ ] After merge: confirm `.github/workflows/release.yml` run succeeds in the Actions tab and creates tag `v1.1.0` + a GitHub Release
EOF
)"
```

- [ ] **Step 3: After merge, verify the release workflow actually ran**

Run: `gh run list --workflow=release.yml --limit 1` and `git ls-remote --tags origin`
Expected: the latest `release.yml` run has conclusion `success`, and `v1.1.0` appears in the
remote tags list (this PR's title is `feat: ...`, so it bumps MINOR from `v1.0.0`). Also check
`gh release view v1.1.0` shows auto-generated notes referencing this PR.

---

## Self-Review Notes

- **Spec coverage:** versioning scheme (Task 5 step 1, Task 1), repo settings change (Task 5
  step 2), PR title lint (Task 3), release workflow incl. skip-list and fail-safe parsing (Task
  1 + Task 2), bootstrap (Task 5 step 1), README/no-CHANGELOG (Task 4), non-goals (no
  `main.py`/`deploy.yml` touched — confirmed no task modifies them; no branch protection —
  confirmed Task 5 only sets merge-method restriction, not a protection rule). All spec sections
  are covered.
- **Placeholder scan:** no TBD/TODO; every step has literal file contents or exact commands.
- **Type consistency:** the 11-type list matches verbatim between `compute-version-bump.sh`
  (Task 1), `pr-title-lint.yml` (Task 3), and the README (Task 4). The `level`/`tag` output
  contract from Task 1 is consumed with the same field names in Task 2's workflow.
