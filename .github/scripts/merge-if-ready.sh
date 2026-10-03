#!/usr/bin/env bash
# Merged einen Agent-PR nach main, wenn alle Gates erfüllt sind. Deterministisch, kein LLM.
# Aufruf: merge-if-ready.sh <pr-nummer>      (GH_TOKEN = AGENT_PAT, damit der Merge Folge-Workflows auslöst)
# Gates: offen, kein Draft, gleiches Repo, Branch agent/*, Label review:approved (gilt nur für den
# letzten Commit, weil agent-review.yml es bei jedem Push entfernt), kein needs-human,
# keine Konflikte, CI-Workflow vollständig grün.
set -euo pipefail
pr="$1"

info() { gh pr view "$pr" --json state,isDraft,isCrossRepository,headRefName,mergeable,labels; }

for i in 1 2 3 4 5; do
  j=$(info)
  [ "$(jq -r .mergeable <<<"$j")" != "UNKNOWN" ] && break
  sleep 6
done

state=$(jq -r .state <<<"$j")
branch=$(jq -r .headRefName <<<"$j")
labels=$(jq -r '[.labels[].name]|join(",")' <<<"$j")

skip() { echo "PR #$pr: übersprungen – $1"; exit 0; }
[ "$state" = "OPEN" ]                          || skip "nicht offen"
[ "$(jq -r .isDraft <<<"$j")" = "false" ]      || skip "Draft"
[ "$(jq -r .isCrossRepository <<<"$j")" = "false" ] || skip "Fork-PR"
[[ "$branch" == agent/* ]]                     || skip "kein Agent-Branch"
[[ ",$labels," == *",review:approved,"* ]]     || skip "nicht vom Reviewer freigegeben"
[[ ",$labels," != *",needs-human,"* ]]         || skip "needs-human"
[[ ",$labels," != *",review:changes-requested,"* ]] || skip "Änderungen angefordert"

if [ "$(jq -r .mergeable <<<"$j")" = "CONFLICTING" ]; then
  gh pr edit "$pr" --add-label needs-human
  gh pr comment "$pr" --body "Merge-Konflikt mit main. Bitte manuell auflösen."
  skip "Konflikt"
fi

# Nur der CI-Workflow zählt (die Agent-Workflows selbst laufen auf demselben PR).
checks=$(gh pr checks "$pr" --json workflow,bucket 2>/dev/null || echo '[]')
ci=$(jq '[.[]|select(.workflow=="CI")]' <<<"$checks")
[ "$(jq length <<<"$ci")" -gt 0 ] || skip "CI noch nicht gestartet"
if [ "$(jq '[.[]|select(.bucket=="fail" or .bucket=="cancel")]|length' <<<"$ci")" -gt 0 ]; then
  gh pr edit "$pr" --add-label needs-human
  gh pr comment "$pr" --body "CI ist fehlgeschlagen, kein automatischer Merge."
  skip "CI rot"
fi
[ "$(jq '[.[]|select(.bucket=="pending")]|length' <<<"$ci")" -eq 0 ] || skip "CI läuft noch"

echo "PR #$pr: alle Gates erfüllt, merge"
gh pr merge "$pr" --squash --delete-branch
