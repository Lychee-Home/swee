# Deployment details

Deep-dive reference for `swee`'s CI/CD and release process. See the [README](../README.md#deployment)
for the quick-start version.

## Continuous deployment

Pushes to `main` auto-deploy via `.github/workflows/deploy.yml`, which runs on a self-hosted
GitHub Actions runner installed on the same host as the bot (see [GitHub's
docs](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners)
for installing the runner itself). On each push the runner `cd`s into the deployed repo,
specified by the **required** `SWEE_DIR` repo variable (the canonical absolute path to the deployed
repo — no trailing slash or symlinks, matching what `deploy/setup.sh` resolves via `cd ... && pwd`),
does a `git pull --ff-only`, reinstalls dependencies, and restarts `swee.service`. No
inbound access to the host is required since the runner polls GitHub outbound; `deploy/setup.sh`
installs the passwordless-sudo rule (`systemctl restart swee`) the workflow needs to restart the
service non-interactively.

By default the runner is assumed to run as the same OS user `swee` itself runs as (matching
`deploy/setup.sh`'s default). To run the GitHub Actions runner as a separate, dedicated OS user instead
(recommended once this host runs apps beyond this one) — so the runner never needs direct file access to
any app's directory — set both of the following together:

- Run `deploy/setup.sh` with `RUNNER_USER=<runner's OS user>` set, e.g.
  `RUNNER_USER=github-runner ./deploy/setup.sh`. This grants `<runner's OS user>` passwordless sudo to run
  `deploy/ci-deploy.sh` as `swee`'s own OS user, and to restart `swee.service`.
- Set the `SWEE_USER` repo variable (alongside the existing `SWEE_DIR`) to `swee`'s own OS user. This
  tells `deploy.yml` to delegate deploys via `sudo -u "$SWEE_USER" -H "$SWEE_DIR/deploy/ci-deploy.sh"` instead of running
  `git pull`/`pip install` directly.

Leave both unset to keep the current single-user behavior, where the runner's own OS user must already
have write access to `$SWEE_DIR`. `swee.service`'s own `User=` and the bot's own Palworld-restart sudo
rule are unaffected either way — only the CI identity changes.

## Versioning

Releases are tagged automatically. Every PR title must follow [Conventional
Commits](https://www.conventionalcommits.org/) format (`feat: ...`, `fix: ...`, `chore: ...`,
etc. — enforced by a PR check, though not merge-blocking). Squash merge is the only allowed
merge method, so each PR becomes exactly one commit on `main` titled with its PR title.

On push to `main`, `.github/workflows/release.yml` reads that commit's type:
- `feat` bumps MINOR, `fix`/`perf` bump PATCH, and a `!` after the type/scope (or a line in the
  PR description that starts with `BREAKING CHANGE:`) bumps MAJOR — each creates a new
  `vX.Y.Z` tag and GitHub Release with auto-generated notes. The footer must start a line;
  merely mentioning the phrase elsewhere in the description doesn't trigger it.
- Any other type (`docs`, `chore`, `ci`, `style`, `test`, `refactor`, `build`, `revert`) merges
  without a release.

Reserve `!`/`BREAKING CHANGE:` for changes that break an existing deployment on upgrade — e.g. a
new required `.env` var, a removed/renamed slash command, a changed REST config shape.
