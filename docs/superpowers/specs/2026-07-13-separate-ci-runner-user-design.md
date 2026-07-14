# Separate CI runner user — design

## Problem

`deploy/setup.sh` infers the OS user it operates as via `SWEE_USER="$(whoami)"` (`deploy/setup.sh:15`)
and uses that single value for three distinct roles: the user `swee.service` runs as (`deploy/swee.service`'s
`User=` directive), the user the bot process itself needs passwordless sudo as (to restart the Palworld
service via `/restart` and RAM auto-restart), and — implicitly, via `.github/workflows/deploy.yml`'s
`${SWEE_DIR:-$HOME/swee}` fallback and its bare `git pull`/`pip install`/`sudo systemctl restart swee`
commands — the user the self-hosted GitHub Actions runner itself runs as.

This host is being set up to eventually run apps beyond the Palworld Discord bot, unrelated to the
`steam` user the bot and Palworld server run as. Continuing to assume "runner user == app user" means
either running the CI runner as `steam` (coupling an unrelated app's deploy identity to the Palworld
service account) or re-deriving a users/permissions scheme by hand for every future app.

## Scope

- Decouple the self-hosted runner's OS user from `swee`'s own OS user (`steam`), for `swee` specifically.
- Establish the pattern (dedicated runner user, per-app `sudo -u <app_user>` delegation scoped to one
  fixed deploy script) that future unrelated apps on this host would replicate in their own repos.
- Preserve exact current behavior when the new configuration isn't set, so this ships without disrupting
  the existing single-user deployment.

Out of scope:
- A shared/reusable provisioning tool spanning multiple apps' repos — deferred until a second app
  actually exists, per YAGNI.
- Installing/configuring the GitHub Actions runner service itself as a new OS user — that remains a
  one-time, human-driven host step per [GitHub's self-hosted runner
  docs](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners),
  same as today.
- Changing who `swee.service` or the bot process itself runs as (`steam` stays `steam`) — only the CI
  identity changes.

## Components

### 1. `deploy/setup.sh` — optional `RUNNER_USER` input

Read from the environment when invoking the script (e.g. `RUNNER_USER=github-runner ./deploy/setup.sh`),
not from `.env` — it's a one-time setup-time input, not app runtime config:

```bash
RUNNER_USER="${RUNNER_USER:-}"
```

**If `RUNNER_USER` is unset** (today's usage, unchanged): both existing sudoers files
(`/etc/sudoers.d/swee-palworld-restart`, `/etc/sudoers.d/swee-self-restart`) stay scoped to `$SWEE_USER`
exactly as today (`deploy/setup.sh:58-70`, `:72-84`). No new files are installed.

**If `RUNNER_USER` is set**:
- `swee-palworld-restart` is **unaffected** — still scoped to `$SWEE_USER`. This rule is for the bot
  process itself (running as `$SWEE_USER` per `swee.service`'s `User=`) to restart Palworld; the runner
  never touches it.
- `swee-self-restart`'s line changes from `$SWEE_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart swee`
  to `$RUNNER_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart swee` — since it's now the runner,
  not `$SWEE_USER`, that calls this from CI.
- A new sudoers file, `/etc/sudoers.d/swee-ci-deploy`, is installed:
  ```
  $RUNNER_USER ALL=($SWEE_USER) NOPASSWD: $SWEE_DIR/deploy/ci-deploy.sh
  ```
  This grants the runner permission to run exactly one fixed-path script *as* `$SWEE_USER` — not a
  wildcarded `git`/`pip` command set, which would be fragile to match exactly and easy to over-grant via
  a loose wildcard.
- `deploy/ci-deploy.sh` (Component 2) is installed executable: `chmod +x deploy/ci-deploy.sh`.

The existing idempotent pattern (diff installed sudoers content against the desired line, rewrite only if
different — `deploy/setup.sh:61-70`, `:75-84`) is reused unchanged for all three files. Re-running
`setup.sh` with `RUNNER_USER` newly set, changed, or removed self-heals all three files to the correct
target user on the next run.

### 2. `deploy/ci-deploy.sh` (new file)

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
git pull --ff-only origin main
.venv/bin/pip install -q -r requirements.txt
```

Identical to today's `git pull`/`pip install` lines in `deploy.yml` (`.github/workflows/deploy.yml:20-21`),
extracted into a standalone script so the sudoers rule in Component 1 can reference one fixed path instead
of individually whitelisting `git`/`pip` invocations with wildcarded arguments.

### 3. `.github/workflows/deploy.yml` — conditional delegation

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

Two changes from today:
- `SWEE_DIR` is now **required** — the `${SWEE_DIR:-$HOME/swee}` fallback is removed. Once the runner is
  a separate user, `$HOME` resolves to the *runner's* home, not `steam`'s, so the old fallback would
  silently deploy to (or fail against) the wrong directory. Failing fast with a clear message is safer
  than a silently wrong default.
- A new `vars.SWEE_USER` repo variable is the on/off switch for "separate runner" mode, mirroring
  `setup.sh`'s `RUNNER_USER` on/off switch:
  - **Set** → delegate via `sudo -u "$SWEE_USER" -H deploy/ci-deploy.sh` (requires `setup.sh` to have been
    run with a matching `RUNNER_USER`, which installed the `swee-ci-deploy` sudoers rule).
  - **Unset** → run `git pull`/`pip install` directly, exactly as today (requires the runner's own OS
    user to already have write access to `SWEE_DIR` — i.e. runner user == `SWEE_USER`, today's assumption).

### 4. `README.md`

Add a subsection under "Continuous deployment" documenting:
- The two repo variables, `SWEE_DIR` (now required) and `SWEE_USER` (optional, enables delegation mode).
- The `RUNNER_USER` env var for `deploy/setup.sh`, and that it must be set consistently with `vars.SWEE_USER`
  for delegation mode to work (both set, or both left unset).
- That `swee.service`'s `User=` and the bot's own Palworld-restart sudo rule are unaffected by any of this
  — only the CI identity changes.

## Error handling

- `SWEE_DIR` unset in `deploy.yml`: the `: "${SWEE_DIR:?...}"` guard fails the step immediately with an
  explicit message, instead of falling back to a directory that may not exist or may belong to the wrong
  user.
- `vars.SWEE_USER` set but `setup.sh` was never run with a matching `RUNNER_USER` (no `swee-ci-deploy`
  sudoers rule installed): `sudo -u` fails immediately with a permission-denied error in the Action's
  logs — `NOPASSWD` mismatches cause `sudo` to refuse outright in a non-interactive shell rather than hang
  waiting for a password, so the failure is loud and immediate, not silent.
- `vars.SWEE_USER` unset but the runner's OS user actually differs from `steam` (misconfiguration): `git
  pull`/`pip install` fail with ordinary filesystem permission errors, same class of failure as today if
  `SWEE_DIR` were ever wrong — no new failure mode introduced.

## Non-goals / risks accepted

- No shared tooling across apps yet — the next app that needs this pattern replicates
  `ci-deploy.sh`/`swee-ci-deploy`-equivalent files by hand in its own repo. Revisit extracting a shared
  provisioning script once a second app actually exists, not speculatively now.
- `sudo -u "$SWEE_USER" -H` runs `ci-deploy.sh` with `$SWEE_USER`'s `$HOME` (via `-H`), so `git`/`pip`
  behave as if invoked by `steam` directly (respecting `steam`'s git config, pip cache, etc.) — this
  matches today's behavior where the runner already ran these commands directly as `steam`.
- If someone sets `vars.SWEE_USER` without ever running `setup.sh` with a matching `RUNNER_USER` (or vice
  versa), the two modes silently diverge until the next deploy attempt surfaces a permission error. This
  is a one-time setup-consistency requirement documented in the README (Component 4), not something the
  scripts detect and cross-check automatically — accepted as low-risk since it only affects the *initial*
  transition to delegation mode, not steady-state operation.
