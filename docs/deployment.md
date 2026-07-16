# Deployment details

Deep-dive reference for `swee`'s CI/CD and release process. See the [README](../README.md#deployment)
for the quick-start version.

## Continuous deployment

`.github/workflows/ci.yml` runs on every push to `main`. Its `release-please` job (see
Versioning below) determines whether that push produced a new release; only when it did does
the `deploy` job run, on a self-hosted GitHub Actions runner installed on the same host as the
bot (see [GitHub's
docs](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners)
for installing the runner itself). Merging an ordinary feature PR to `main` does **not** deploy
by itself — see Versioning below for what does. When `deploy` runs, it `cd`s into the deployed
repo, specified by the **required** `SWEE_DIR` repo variable (the canonical absolute path to the
deployed repo — no trailing slash or symlinks, matching what `deploy/setup.sh` resolves via
`cd ... && pwd`), does a `git pull --ff-only`, reinstalls dependencies, and restarts
`swee.service`. No inbound access to the host is required since the runner polls GitHub
outbound; `deploy/setup.sh` installs the passwordless-sudo rule (`systemctl restart swee`) the
workflow needs to restart the service non-interactively.

By default the runner is assumed to run as the same OS user `swee` itself runs as (matching
`deploy/setup.sh`'s default). To run the GitHub Actions runner as a separate, dedicated OS user instead
(recommended once this host runs apps beyond this one) — so the runner never needs direct file access to
any app's directory — set both of the following together:

- Run `deploy/setup.sh` with `RUNNER_USER=<runner's OS user>` set, e.g.
  `RUNNER_USER=github-runner ./deploy/setup.sh`. This grants `<runner's OS user>` passwordless sudo to run
  `deploy/ci-deploy.sh` as `swee`'s own OS user, and to restart `swee.service`.
- Set the `SWEE_USER` repo variable (alongside the existing `SWEE_DIR`) to `swee`'s own OS user. This
  tells `ci.yml` to delegate deploys via `sudo -u "$SWEE_USER" -H "$SWEE_DIR/deploy/ci-deploy.sh"` instead of running
  `git pull`/`pip install` directly.

Leave both unset to keep the current single-user behavior, where the runner's own OS user must already
have write access to `$SWEE_DIR`. `swee.service`'s own `User=` and the bot's own Palworld-restart sudo
rule are unaffected either way — only the CI identity changes.

## Versioning

Releases are managed by [`release-please`](https://github.com/googleapis/release-please) via
the `release-please` job in `.github/workflows/ci.yml`, using Conventional Commits
(`feat: ...`, `fix: ...`, `chore: ...`, etc.) parsed from commits on `main`.

On every push to `main`, release-please updates a standing **Release PR** (title like
`chore(main): release X.Y.Z`) with the accumulated version bump and `CHANGELOG.md` entries:
`feat` bumps MINOR, `fix`/`perf` bump PATCH, and a `!` after the type/scope (or a
`BREAKING CHANGE:` footer starting its own line in the commit body) bumps MAJOR. Any other type
(`docs`, `chore`, `ci`, `style`, `test`, `refactor`, `build`, `revert`) doesn't contribute a
version bump, though it may still appear in the changelog depending on release-please's default
section mapping.

**Nothing ships until you merge that Release PR.** Merging it is what tags the release, publishes
the GitHub Release, and — via the `deploy` job's dependency on `release_created` — triggers the
actual deploy. Ordinary feature PRs merging to `main` only update the Release PR's diff; they
don't deploy or release anything by themselves.

Reserve `!`/`BREAKING CHANGE:` for changes that break an existing deployment on upgrade — e.g. a
new required `.env` var, a removed/renamed slash command, a changed REST config shape.
