#!/usr/bin/env bash
# Hilfsskript für den Konflikt-Job in agent-merge.yml. Das LLM löst nur Konfliktmarker in der
# Allowlist-Datei; Auswahl, Prüfung, Commit und Push sind deterministisch.
#   resolve-conflicts.sh prepare   findet einen freigegebenen, konfliktbehafteten PR, merged main
#                                  in den PR-Branch und schreibt pr/branch/needs_llm nach $GITHUB_OUTPUT
#   resolve-conflicts.sh finish <pr> <branch>
#                                  prüft das Ergebnis, committet den Merge und pusht
# Aufruf mit GH_TOKEN = AGENT_PAT (Push muss Folge-Workflows auslösen, Review läuft danach neu).
set -euo pipefail

ALLOWED=("pyproject.toml" "Dockerfile" "app/pipeline/preprocess.py")   # nur diese Dateien darf das LLM auflösen; alles andere -> needs-human
MAX_ATTEMPTS=2
MARKER="<!-- auto-conflict-resolve -->"

out() { echo "$1=$2" >> "${GITHUB_OUTPUT:-/dev/null}"; }
human() { # <pr> <grund>
  gh pr edit "$1" --add-label needs-human
  gh pr comment "$1" --body "Merge-Konflikt mit main, automatische Auflösung nicht möglich: $2"
}
is_allowed() { local f; for f in "${ALLOWED[@]}"; do [ "$f" = "$1" ] && return 0; done; return 1; }

git config user.name "planklar-agent"
git config user.email "planklar-agent@users.noreply.github.com"

mode="${1:?prepare|finish}"

if [ "$mode" = "prepare" ]; then
  out pr ""
  for pr in $(gh pr list --state open --label review:approved --json number -q '.[].number'); do
    j=$(gh pr view "$pr" --json mergeable,isDraft,isCrossRepository,headRefName,labels,comments)
    [ "$(jq -r .mergeable <<<"$j")" = "CONFLICTING" ] || continue
    [ "$(jq -r .isCrossRepository <<<"$j")" = "false" ] || continue
    branch=$(jq -r .headRefName <<<"$j")
    [[ "$branch" == agent/* ]] || continue
    [ "$(jq '[.labels[].name]|index("needs-human")' <<<"$j")" = "null" ] || continue

    attempts=$(jq --arg m "$MARKER" '[.comments[]|select(.body|contains($m))]|length' <<<"$j")
    if [ "$attempts" -ge "$MAX_ATTEMPTS" ]; then human "$pr" "$attempts Versuche ohne Erfolg."; continue; fi

    git fetch origin main "$branch"
    git checkout -B "$branch" "origin/$branch"
    if git merge --no-commit --no-ff origin/main >/dev/null 2>&1; then
      # Git löst es selbst (z. B. main hat sich inzwischen bewegt): normal committen
      git commit -m "merge: main in $branch"
      git push origin "HEAD:$branch"
      gh pr comment "$pr" --body "$MARKER Konflikt ohne Eingriff aufgelöst (main eingemerged)."
      continue
    fi
    conflicted=$(git diff --name-only --diff-filter=U)
    bad=""
    for f in $conflicted; do is_allowed "$f" || bad="$bad $f"; done
    if [ -n "$bad" ]; then
      git merge --abort
      human "$pr" "Konflikt in Dateien ausserhalb der Allowlist:$bad"
      continue
    fi
    echo "PR #$pr: Konflikt nur in: $conflicted"
    out pr "$pr"; out branch "$branch"; out files "$(echo $conflicted)"
    exit 0
  done
  exit 0
fi

if [ "$mode" = "finish" ]; then
  pr="$2"; branch="$3"
  gh pr comment "$pr" --body "$MARKER Versuch, den Konflikt automatisch aufzulösen."
  fail() { git merge --abort 2>/dev/null || true; human "$pr" "$1"; exit 0; }

  # Die Prüfungen laufen nur für Dateien, die tatsächlich im Konflikt standen
  conflicted=$(git diff --name-only --diff-filter=U)
  for f in $conflicted; do
    is_allowed "$f" || fail "Datei ausserhalb der Allowlist im Konflikt: $f"
    # Keine Konfliktmarker mehr
    ! grep -qE '^(<<<<<<<|=======|>>>>>>>)' "$f" || fail "Konfliktmarker in $f verblieben."
  done

  # Nichts darf verloren gehen: Das Ergebnis muss alles enthalten, was main UND der PR kennen.
  # check_kept <datei> <extraktor>: Extraktor liest eine Datei (Argument 1) und gibt je Zeile ein Element aus.
  check_kept() {
    local f="$1" lost
    git show "origin/main:$f" > "$RUNNER_TEMP/main.side"
    git show "origin/$branch:$f" > "$RUNNER_TEMP/pr.side"
    lost=$(python - "$RUNNER_TEMP/main.side" "$RUNNER_TEMP/pr.side" "$f" "$2" <<'PY'
import ast, re, sys, tomllib

def toml_deps(path):
    p = tomllib.load(open(path, "rb")).get("project", {})
    items = list(p.get("dependencies", []))
    for v in p.get("optional-dependencies", {}).values():
        items += v
    return {re.split(r"[<>=!~\[ ;]", i, maxsplit=1)[0].lower() for i in items}

def py_defs(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}

def apt_packages(path):
    text = open(path, encoding="utf-8").read().replace("\\\n", " ")
    pk = set()
    for m in re.finditer(r"apt-get install\b([^&;\n]*)", text):
        pk |= {t for t in m.group(1).split() if not t.startswith("-")}
    return pk

main, pr, merged, kind = sys.argv[1:5]
fn = {"toml": toml_deps, "py": py_defs, "apt": apt_packages}[kind]
print(" ".join(sorted((fn(main) | fn(pr)) - fn(merged))))
PY
) || fail "$f ist nach der Auflösung nicht lesbar (ungültiges TOML bzw. Python)."
    [ -z "$lost" ] || fail "In $f gingen Einträge verloren: $lost"
  }
  for f in $conflicted; do
    case "$f" in
      pyproject.toml)              check_kept "$f" toml ;;
      app/pipeline/preprocess.py)  check_kept "$f" py ;;
      Dockerfile)                  check_kept "$f" apt ;;
    esac
  done

  git add $conflicted
  [ -z "$(git diff --name-only --diff-filter=U)" ] || fail "Weitere ungelöste Konflikte."
  git commit -m "merge: main in $branch (Konflikt automatisch aufgelöst)"
  git push origin "HEAD:$branch"
  gh pr comment "$pr" --body "$MARKER Konflikt in $(echo $conflicted) aufgelöst und gepusht. Der Reviewer prüft den neuen Stand erneut."
fi
