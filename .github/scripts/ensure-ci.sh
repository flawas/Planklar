#!/usr/bin/env bash
# Stellt sicher, dass nach einem Agent-Lauf die Folge-Workflows (CI, Review) für den Branch laufen.
# Aufruf: ensure-ci.sh <branch>      (GH_TOKEN = AGENT_PAT, GH_REPO = owner/repo)
# Hintergrund: Pushes mit dem Standard-Token (so pusht claude-code-action teils selbst) lösen keine
# Workflows aus. Das Skript pusht übrige lokale Commits mit dem PAT und öffnet den PR neu, falls für
# den Branch-Stand kein pull_request-Lauf existiert (reopened startet CI und Review).
set -euo pipefail
branch="$1"

git remote set-url origin "https://x-access-token:${GH_TOKEN}@github.com/${GH_REPO}.git"
git fetch -q origin "$branch" || { echo "Branch $branch existiert nicht, nichts zu tun."; exit 0; }

if [ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$branch")" ] \
   && git merge-base --is-ancestor "origin/$branch" HEAD; then
  git push origin "HEAD:$branch"
  git fetch -q origin "$branch"
fi
sha=$(git rev-parse "origin/$branch")

pr=$(gh pr list --head "$branch" --state open --json number -q '.[0].number // empty')
[ -n "$pr" ] || { echo "Kein offener PR für $branch."; exit 0; }

# Läufe brauchen einen Moment, bis sie erscheinen
runs=0
for _ in 1 2 3 4 5 6; do
  sleep 10
  runs=$(gh run list --branch "$branch" --commit "$sha" --json event -q '[.[]|select(.event=="pull_request")]|length')
  [ "$runs" -eq 0 ] || break
done

if [ "$runs" -eq 0 ]; then
  echo "Kein Lauf für ${sha:0:7}, PR #$pr wird neu geöffnet."
  gh pr close "$pr"
  sleep 3
  gh pr reopen "$pr"
fi
