#!/usr/bin/env bash
# Setzt status:blocked -> status:ready, wenn alle "Depends on: #N" geschlossen sind.
# Deterministisch, ohne LLM. Braucht GH_TOKEN mit einem PAT/App-Token, damit das
# Label-Event die Dev-Workflows auslöst (GITHUB_TOKEN-Events tun das nicht).
set -euo pipefail

gh issue list --label "status:blocked" --state open --limit 200 --json number,body |
jq -c '.[]' | while read -r issue; do
  num=$(jq -r .number <<<"$issue")
  deps=$(jq -r '.body // ""' <<<"$issue" | grep -iE '^depends on:' | grep -oE '#[0-9]+' | tr -d '#' || true)
  open_dep=0
  for d in $deps; do
    state=$(gh issue view "$d" --json state -q .state 2>/dev/null || echo OPEN)
    [ "$state" = "CLOSED" ] || open_dep=1
  done
  if [ "$open_dep" -eq 0 ]; then
    echo "Entsperre #$num"
    gh issue edit "$num" --remove-label "status:blocked" --add-label "status:ready"
  fi
done
