"""Aufruf: `python -m eval.run --model <name>` (manuell oder wöchentlich, nie im PR-CI).

Echte Modellaufrufe über LiteLLM; Modell und Schlüssel wie im Betrieb (`LLM_API_KEY`).
Exit-Code 1, wenn ein Gate nicht erreicht wird, 2 bei ungültigem Evaluations-Set.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from app.config import get_settings
from app.pipeline.llm import LLMClient
from eval.harness import DataError, evaluate, load_seiten, to_json, to_markdown

DEFAULT_DATA = Path(__file__).parent / "data"
DEFAULT_OUT = Path(__file__).parent / "reports"


def main(argv: Sequence[str] | None = None, *, client: LLMClient | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.run", description=__doc__)
    parser.add_argument("--model", required=True, help="LiteLLM-Modellname")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    try:
        seiten = load_seiten(args.data)
    except DataError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    if client is None:
        # Das Modell kommt aus den Settings (`LLM_MODEL`); hier für diesen Lauf überschrieben.
        settings = get_settings()
        previous = settings.llm_model
        settings.llm_model = args.model
    try:
        result = evaluate(seiten, model=args.model, client=client)
    finally:
        if client is None:
            settings.llm_model = previous

    args.out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", args.model)
    (args.out / f"{stem}.json").write_text(
        json.dumps(to_json(result), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    markdown = to_markdown(result)
    (args.out / f"{stem}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
