"""Quellen-URLs des Regelkatalogs auf Änderungen prüfen.

Nur vom Workflow `rules-source-check.yml` aufgerufen (dort ist Netzwerk erlaubt). Ändert nie Regeln:
Das Ergebnis ist ein Bericht für einen Menschen.
Referenzstand: `rules/.source-hashes.json` (URL -> SHA-256).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = ROOT / "rules"
HASH_FILE = RULES_DIR / ".source-hashes.json"
TIMEOUT_S = 30

Fetcher = Callable[[str], bytes]


def collect_urls(rules_dir: Path) -> dict[str, list[str]]:
    """URL -> Regel-IDs, die sich darauf stützen."""
    urls: dict[str, list[str]] = {}
    for path in sorted(rules_dir.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        for rule in data if isinstance(data, list) else []:
            url = (rule.get("quelle") or {}).get("url")
            if url:
                urls.setdefault(url, []).append(str(rule.get("id")))
    return urls


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "liquet-source-check"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 (nur http/https per Schema)
        body: bytes = resp.read()
    return body


def check(
    urls: dict[str, list[str]], stored: dict[str, str], fetcher: Fetcher
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Gibt (Befunde nach Art, aktuelle Hashes) zurück. Art: geaendert, ohne_referenz, fehler."""
    findings: dict[str, list[str]] = {"geaendert": [], "ohne_referenz": [], "fehler": []}
    current: dict[str, str] = {}
    for url in sorted(urls):
        try:
            digest = hashlib.sha256(fetcher(url)).hexdigest()
        except Exception as exc:  # jeder Abruffehler ist ein Befund, nie ein Abbruch
            findings["fehler"].append(f"{url} ({type(exc).__name__})")
            continue
        current[url] = digest
        if url not in stored:
            findings["ohne_referenz"].append(url)
        elif stored[url] != digest:
            findings["geaendert"].append(url)
    return findings, current


def render_report(findings: dict[str, list[str]], urls: dict[str, list[str]]) -> str:
    titles = {
        "geaendert": "Inhalt geändert",
        "ohne_referenz": "Kein gespeicherter Stand",
        "fehler": "Abruf fehlgeschlagen",
    }
    lines = [
        "Prüfung der Quellen-URLs im Regelkatalog. Es wurde nichts automatisch geändert.",
        "",
    ]
    for kind, title in titles.items():
        if not findings[kind]:
            continue
        lines.append(f"## {title}")
        for entry in findings[kind]:
            url = entry.split(" ", 1)[0]
            lines.append(f"- {entry} – Regeln: {', '.join(urls.get(url, []))}")
        lines.append("")
    lines += [
        "Vorgehen: Quelle manuell prüfen, Regeln und `stand` bei Bedarf anpassen, danach",
        "`python -m app.rules.source_check --update` ausführen und",
        "`rules/.source-hashes.json` committen.",
        "Hinweis: Dynamische Seiten können den Hash ohne inhaltliche Änderung verändern.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Iterable[str] | None = None, fetcher: Fetcher = fetch) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules-dir", type=Path, default=RULES_DIR)
    parser.add_argument("--hash-file", type=Path, default=HASH_FILE)
    parser.add_argument(
        "--report", type=Path, help="Markdown-Bericht (nur bei Befunden geschrieben)"
    )
    parser.add_argument(
        "--update", action="store_true", help="Referenzstand neu schreiben (manuell)"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    urls = collect_urls(args.rules_dir)
    stored: dict[str, str] = {}
    if args.hash_file.exists():
        stored = json.loads(args.hash_file.read_text(encoding="utf-8"))
    findings, current = check(urls, stored, fetcher)

    if args.update:
        # Fehlgeschlagene Abrufe behalten ihren bisherigen Referenzstand.
        merged = {u: stored[u] for u in urls if u in stored} | current
        args.hash_file.write_text(
            json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"{len(merged)} Hashes nach {args.hash_file} geschrieben")
        return 1 if findings["fehler"] else 0

    if not any(findings.values()):
        print(f"{len(urls)} Quellen unverändert")
        return 0
    report = render_report(findings, urls)
    print(report)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    return 1


if __name__ == "__main__":
    sys.exit(main())
