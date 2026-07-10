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
