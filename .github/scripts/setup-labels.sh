#!/usr/bin/env bash
# Legt alle Labels an, die die Agent-Pipeline braucht. Idempotent.
# Aufruf: .github/scripts/setup-labels.sh   (gh muss eingeloggt sein)
set -euo pipefail

mk() { gh label create "$1" --color "$2" --description "$3" --force >/dev/null && echo "ok  $1"; }

for r in architect backend pipeline rules frontend devops qa; do
  mk "agent:$r" "1d76db" "Wird vom Agent '$r' bearbeitet"
done
for p in 0 1 2 3 4 5; do mk "phase:$p" "c5def5" "Phase $p des Phasenplans"; done

mk "status:ready"       "0e8a16" "Bereit: Agent startet"
mk "status:blocked"     "fbca04" "Wartet auf Abhängigkeiten (Depends on: #N)"
mk "status:in-progress" "5319e7" "Agent arbeitet"
mk "review:approved"            "0e8a16" "Reviewer-Agent: ohne blocker/should"
mk "review:changes-requested"   "d93f0b" "Reviewer-Agent: Änderungen nötig"
mk "needs-human"        "b60205" "Entscheidung oder Eingriff durch Mensch nötig"
