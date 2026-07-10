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

has_breaking_footer=false
while IFS= read -r line; do
  if [[ "$line" == "BREAKING CHANGE:"* ]]; then
    has_breaking_footer=true
    break
  fi
done <<< "$body"

if [[ -n "$breaking_marker" || "$has_breaking_footer" == true ]]; then
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
