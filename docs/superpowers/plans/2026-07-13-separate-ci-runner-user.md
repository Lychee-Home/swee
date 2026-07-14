# Separate CI Runner User Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the self-hosted GitHub Actions runner run as its own dedicated OS user, separate from `steam` (the user `swee`/Palworld run as), via an optional `RUNNER_USER`/`vars.SWEE_USER` delegation mode that's a no-op when unset.

**Architecture:** A new fixed-path script (`deploy/ci-deploy.sh`) holds the git-pull/pip-install steps. `deploy/setup.sh` optionally grants a separate runner user passwordless sudo to run that one script as the app user (`sudo -u`), plus to restart `swee.service`. `deploy.yml` picks between direct execution (today's behavior) and `sudo -u` delegation based on whether `vars.SWEE_USER` is set.

**Tech Stack:** bash (`deploy/setup.sh`, `deploy/ci-deploy.sh`), GitHub Actions workflow YAML (`.github/workflows/deploy.yml`), systemd/sudoers (via `deploy/setup.sh`).

## Global Constraints

- When `RUNNER_USER` (setup.sh) and `vars.SWEE_USER` (deploy.yml) are both left unset, behavior must be byte-for-byte identical to today — this is the default path for the existing single-user deployment.
- `deploy/setup.sh`'s existing idempotent pattern (diff installed sudoers content vs. desired line, rewrite only if different) must be reused for any new/changed sudoers file — do not introduce a different mechanism.
- No automated test runner exists in this repo — verification uses `bash -n`, `grep`, and manual structural review, not a test suite.
- Never push to `main` directly — all commits in this plan go to the existing branch `separate-ci-runner-user`.

---

### Task 1: `deploy/ci-deploy.sh` — new fixed-path deploy script

**Files:**
- Create: `deploy/ci-deploy.sh`

**Interfaces:**
- Produces: an executable script at a fixed path (`$SWEE_DIR/deploy/ci-deploy.sh` once installed on a host), taking no arguments, that `cd`s to the repo root and does `git pull --ff-only origin main` then `.venv/bin/pip install -q -r requirements.txt`. Task 2's sudoers rule and Task 3's `deploy.yml` change both reference this exact path.

- [ ] **Step 1: Create the script**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
git pull --ff-only origin main
.venv/bin/pip install -q -r requirements.txt
```

- [ ] **Step 2: Mark it executable in git**

The sandbox/checkout may not preserve the Unix executable bit through a plain file write, so set it explicitly via git's index (this is honored on any platform this repo is cloned to, including the Linux deploy host):

Run: `cd C:/Users/byron/PycharmProjects/swee && git update-index --add --chmod=+x deploy/ci-deploy.sh`

- [ ] **Step 3: Verify syntax and the executable bit**

Run: `cd C:/Users/byron/PycharmProjects/swee && bash -n deploy/ci-deploy.sh && echo "SYNTAX OK"`
Expected: `SYNTAX OK`

Run: `cd C:/Users/byron/PycharmProjects/swee && git ls-files -s deploy/ci-deploy.sh`
Expected: mode `100755` (the leading `100755` — not `100644` — confirms the executable bit is staged).

- [ ] **Step 4: Commit**

```bash
git add deploy/ci-deploy.sh
git commit -m "feat: add deploy/ci-deploy.sh as the CI's fixed-path deploy entrypoint"
```

---

### Task 2: `deploy/setup.sh` — optional `RUNNER_USER` support

**Files:**
- Modify: `deploy/setup.sh:14-17` (add `RUNNER_USER` read), `deploy/setup.sh:72-84` (retarget `swee-self-restart`), new block after it (add `swee-ci-deploy` sudoers file + `chmod +x` on `deploy/ci-deploy.sh`)

**Interfaces:**
- Consumes: `deploy/ci-deploy.sh` from Task 1 (referenced by path in the new sudoers rule).
- Produces: when `RUNNER_USER` is set, a sudoers file `/etc/sudoers.d/swee-ci-deploy` granting
  `$RUNNER_USER ALL=($SWEE_USER) NOPASSWD: $SWEE_DIR/deploy/ci-deploy.sh`, and `swee-self-restart`
  retargeted to `$RUNNER_USER`. Task 3's `deploy.yml` relies on both existing before `vars.SWEE_USER` is
  set for a given deployment.

- [ ] **Step 1: Read `RUNNER_USER` from the environment**

Current (`deploy/setup.sh:14-16`):
```bash
SWEE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SWEE_USER="$(whoami)"
PYTHON_BIN="python3.14"
```

Replace with:
```bash
SWEE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SWEE_USER="$(whoami)"
RUNNER_USER="${RUNNER_USER:-}"
PYTHON_BIN="python3.14"
```

- [ ] **Step 2: Retarget `swee-self-restart` to `$RUNNER_USER` when set**

Current (`deploy/setup.sh:72-84`):
```bash
echo "==> Checking passwordless sudo for 'systemctl restart swee'"
SWEE_SUDOERS_FILE="/etc/sudoers.d/swee-self-restart"
SWEE_SUDOERS_LINE="$SWEE_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart swee"
if [ "$(sudo cat "$SWEE_SUDOERS_FILE" 2>/dev/null || true)" != "$SWEE_SUDOERS_LINE" ]; then
    TMP_SUDOERS="$(mktemp)"
    echo "$SWEE_SUDOERS_LINE" > "$TMP_SUDOERS"
    sudo visudo -cf "$TMP_SUDOERS"
    sudo install -m 440 -o root -g root "$TMP_SUDOERS" "$SWEE_SUDOERS_FILE"
    rm -f "$TMP_SUDOERS"
    echo "    Installed $SWEE_SUDOERS_FILE"
else
    echo "    Already configured, skipping"
fi
```

Replace with:
```bash
CI_RESTART_USER="${RUNNER_USER:-$SWEE_USER}"
echo "==> Checking passwordless sudo for 'systemctl restart swee' (as $CI_RESTART_USER)"
SWEE_SUDOERS_FILE="/etc/sudoers.d/swee-self-restart"
SWEE_SUDOERS_LINE="$CI_RESTART_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart swee"
if [ "$(sudo cat "$SWEE_SUDOERS_FILE" 2>/dev/null || true)" != "$SWEE_SUDOERS_LINE" ]; then
    TMP_SUDOERS="$(mktemp)"
    echo "$SWEE_SUDOERS_LINE" > "$TMP_SUDOERS"
    sudo visudo -cf "$TMP_SUDOERS"
    sudo install -m 440 -o root -g root "$TMP_SUDOERS" "$SWEE_SUDOERS_FILE"
    rm -f "$TMP_SUDOERS"
    echo "    Installed $SWEE_SUDOERS_FILE"
else
    echo "    Already configured, skipping"
fi
```

(When `RUNNER_USER` is unset, `CI_RESTART_USER` falls back to `$SWEE_USER` — identical to today's line.)

- [ ] **Step 3: Add the `swee-ci-deploy` sudoers file, installed only when `RUNNER_USER` is set**

Insert immediately after the block from Step 2 (still before the "Installing systemd unit" section):

```bash
if [ -n "$RUNNER_USER" ]; then
    echo "==> Checking passwordless sudo for '$RUNNER_USER' to run ci-deploy.sh as $SWEE_USER"
    CI_DEPLOY_SUDOERS_FILE="/etc/sudoers.d/swee-ci-deploy"
    CI_DEPLOY_SUDOERS_LINE="$RUNNER_USER ALL=($SWEE_USER) NOPASSWD: $SWEE_DIR/deploy/ci-deploy.sh"
    if [ "$(sudo cat "$CI_DEPLOY_SUDOERS_FILE" 2>/dev/null || true)" != "$CI_DEPLOY_SUDOERS_LINE" ]; then
        TMP_SUDOERS="$(mktemp)"
        echo "$CI_DEPLOY_SUDOERS_LINE" > "$TMP_SUDOERS"
        sudo visudo -cf "$TMP_SUDOERS"
        sudo install -m 440 -o root -g root "$TMP_SUDOERS" "$CI_DEPLOY_SUDOERS_FILE"
        rm -f "$TMP_SUDOERS"
        echo "    Installed $CI_DEPLOY_SUDOERS_FILE"
    else
        echo "    Already configured, skipping"
    fi

    chmod +x "$SWEE_DIR/deploy/ci-deploy.sh"
else
    echo "==> RUNNER_USER not set, skipping separate-runner sudoers setup (CI is assumed to run as $SWEE_USER)"
fi
```

- [ ] **Step 4: Verify syntax and the unaffected-when-unset guarantee**

Run: `cd C:/Users/byron/PycharmProjects/swee && bash -n deploy/setup.sh && echo "SYNTAX OK"`
Expected: `SYNTAX OK`

Run: `cd C:/Users/byron/PycharmProjects/swee && grep -n 'RUNNER_USER\|CI_RESTART_USER\|swee-ci-deploy' deploy/setup.sh`
Expected: matches for the `RUNNER_USER="${RUNNER_USER:-}"` read, the `CI_RESTART_USER="${RUNNER_USER:-$SWEE_USER}"` fallback, and the new `swee-ci-deploy` block — confirming the unset case falls back to `$SWEE_USER` exactly as before this task.

Run: `cd C:/Users/byron/PycharmProjects/swee && grep -n 'palworld-restart' deploy/setup.sh`
Expected: the `swee-palworld-restart` sudoers block is still present and still keyed on `$SWEE_USER` (not `$CI_RESTART_USER` or `$RUNNER_USER`) — confirming this task did not touch the Palworld-restart rule, only the CI-facing `swee-self-restart` and the new `swee-ci-deploy` file.

- [ ] **Step 5: Commit**

```bash
git add deploy/setup.sh
git commit -m "feat: support optional RUNNER_USER for separate CI-runner sudoers delegation"
```

---

### Task 3: `.github/workflows/deploy.yml` — required `SWEE_DIR`, conditional `SWEE_USER` delegation

**Files:**
- Modify: `.github/workflows/deploy.yml` (entire `run:` block)

**Interfaces:**
- Consumes: `deploy/ci-deploy.sh` from Task 1 (invoked by path), and the `swee-ci-deploy`/`swee-self-restart` sudoers rules from Task 2 (must already be installed on the host for the `vars.SWEE_USER`-set path to succeed — this is a deployment-time prerequisite, not something this task can verify from the repo alone).

- [ ] **Step 1: Replace the workflow's env and run block**

Current (`.github/workflows/deploy.yml`, full file):
```yaml
name: Deploy

on:
  push:
    branches: [main]
    paths:
      - main.py
      - requirements.txt

jobs:
  deploy:
    runs-on: self-hosted
    steps:
      - name: Pull latest and restart service
        env:
          SWEE_DIR: ${{ vars.SWEE_DIR }}
        run: |
          set -euo pipefail
          cd "${SWEE_DIR:-$HOME/swee}"
          git pull --ff-only origin main
          .venv/bin/pip install -q -r requirements.txt
          sudo systemctl restart swee
```

Replace with:
```yaml
name: Deploy

on:
  push:
    branches: [main]
    paths:
      - main.py
      - requirements.txt

jobs:
  deploy:
    runs-on: self-hosted
    steps:
      - name: Pull latest and restart service
        env:
          SWEE_DIR: ${{ vars.SWEE_DIR }}
          SWEE_USER: ${{ vars.SWEE_USER }}
        run: |
          set -euo pipefail
          : "${SWEE_DIR:?SWEE_DIR repo variable must be set}"
          if [ -n "${SWEE_USER:-}" ]; then
            sudo -u "$SWEE_USER" -H "$SWEE_DIR/deploy/ci-deploy.sh"
          else
            cd "$SWEE_DIR"
            git pull --ff-only origin main
            .venv/bin/pip install -q -r requirements.txt
          fi
          sudo systemctl restart swee
```

- [ ] **Step 2: Verify structure**

There is no automated YAML linter configured in this repo, so verify by inspection plus targeted greps:

Run: `cd C:/Users/byron/PycharmProjects/swee && grep -n 'SWEE_DIR:?\|vars.SWEE_USER\|sudo -u\|ci-deploy.sh' .github/workflows/deploy.yml`
Expected: four matches — the `: "${SWEE_DIR:?...}"` guard, the `SWEE_USER: ${{ vars.SWEE_USER }}` env mapping, the `sudo -u "$SWEE_USER" -H` line, and the `ci-deploy.sh` invocation.

Run: `cd C:/Users/byron/PycharmProjects/swee && grep -n '\$HOME/swee' .github/workflows/deploy.yml`
Expected: no output — confirms the old `${SWEE_DIR:-$HOME/swee}` fallback is fully removed.

Read the file back (`.github/workflows/deploy.yml`) and confirm by eye: consistent 2-space YAML indentation matching the rest of the file, the `run: |` block's shell lines all indented one level deeper than `run:`, and no tabs.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "feat: require SWEE_DIR and support SWEE_USER-delegated deploys in CI"
```

---

### Task 4: `README.md` — document the two-variable delegation mode

**Files:**
- Modify: `README.md` (the "Continuous deployment" subsection)

**Interfaces:**
- Consumes: nothing — documentation only, describing behavior implemented in Tasks 1-3.

- [ ] **Step 1: Read the current subsection**

Read `README.md` and find the "### Continuous deployment" subsection (documents `$SWEE_DIR`, the runner, and the passwordless-sudo rule for `systemctl restart swee`).

- [ ] **Step 2: Append delegation-mode documentation**

At the end of the "Continuous deployment" subsection, add:

```markdown

By default the runner is assumed to run as the same OS user `swee` itself runs as (matching
`deploy/setup.sh`'s default). To run the GitHub Actions runner as a separate, dedicated OS user instead
(recommended once this host runs apps beyond this one) — so the runner never needs direct file access to
any app's directory — set both of the following together:

- Run `deploy/setup.sh` with `RUNNER_USER=<runner's OS user>` set, e.g.
  `RUNNER_USER=github-runner ./deploy/setup.sh`. This grants `<runner's OS user>` passwordless sudo to run
  `deploy/ci-deploy.sh` as `swee`'s own OS user, and to restart `swee.service`.
- Set the `SWEE_USER` repo variable (alongside the existing `SWEE_DIR`) to `swee`'s own OS user. This
  tells `deploy.yml` to delegate deploys via `sudo -u "$SWEE_USER" deploy/ci-deploy.sh` instead of running
  `git pull`/`pip install` directly.

Leave both unset to keep the current single-user behavior, where the runner's own OS user must already
have write access to `$SWEE_DIR`. `swee.service`'s own `User=` and the bot's own Palworld-restart sudo
rule are unaffected either way — only the CI identity changes.
```

- [ ] **Step 3: Verify**

Run: `cd C:/Users/byron/PycharmProjects/swee && grep -n 'RUNNER_USER\|SWEE_USER' README.md`
Expected: at least the two new mentions from Step 2 are present.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document RUNNER_USER/SWEE_USER CI-delegation mode in README"
```

---

### Task 5: End-to-end review

**Files:** none (verification only)

**Interfaces:** none.

- [ ] **Step 1: Confirm the unset-both-vars path is unchanged**

Run: `cd C:/Users/byron/PycharmProjects/swee && bash -n deploy/setup.sh && bash -n deploy/ci-deploy.sh && echo "SYNTAX OK"`
Expected: `SYNTAX OK`

- [ ] **Step 2: Confirm cross-file naming consistency**

Run: `cd C:/Users/byron/PycharmProjects/swee && grep -rn 'RUNNER_USER\|SWEE_USER' deploy/setup.sh .github/workflows/deploy.yml README.md`
Expected: `RUNNER_USER` appears only in `deploy/setup.sh` and `README.md` (it's a setup.sh-only env var, not a workflow variable); `SWEE_USER` appears in `deploy/setup.sh` (the pre-existing local `whoami` variable — unrelated in name only), `.github/workflows/deploy.yml` (the new `vars.SWEE_USER`), and `README.md`. Confirm by reading the matched lines that `deploy.yml`'s `vars.SWEE_USER` is meant to hold the same value as `deploy/setup.sh`'s local `$SWEE_USER` (`swee`'s OS user, e.g. `steam`) — same concept, coincidentally same name, not a naming bug.

- [ ] **Step 3: Push the branch and open the PR**

```bash
git push -u origin separate-ci-runner-user
gh pr create --title "feat: support a separate CI runner user for deploys" --body "$(cat <<'EOF'
## Summary
- Adds an optional RUNNER_USER (deploy/setup.sh) / vars.SWEE_USER (deploy.yml) delegation mode
  so the GitHub Actions runner can be a dedicated OS user, separate from swee's own OS user.
- Fully backward-compatible: leaving both unset preserves today's exact single-user behavior.
- deploy.yml now requires the SWEE_DIR repo variable explicitly (no more $HOME-based fallback,
  which would silently break once the runner is a separate user).

## Test plan
- [x] bash -n deploy/setup.sh
- [x] bash -n deploy/ci-deploy.sh
- [x] Manual review: grep confirms swee-palworld-restart sudoers rule is untouched by this change
- [ ] On the actual host: run deploy/setup.sh with RUNNER_USER set to the runner's OS user, set the
      SWEE_USER and SWEE_DIR repo variables, and confirm the next push-to-main deploy succeeds via
      the sudo -u delegation path
- [ ] Confirm existing behavior is unaffected on any deployment that leaves RUNNER_USER/vars.SWEE_USER unset

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

(This step needs your go-ahead before running — pushing and opening the PR are visible, hard-to-fully-reverse actions.)