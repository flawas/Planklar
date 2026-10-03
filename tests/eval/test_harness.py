import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from app.pipeline import classify, merkmale
from app.pipeline.llm import RawCompletion
from eval import run
from eval.harness import DataError, evaluate, load_seiten, to_json, to_markdown

PAGES = {
    "p1": {
        "plantyp": "Grundriss",
        "merkmale": {
            "massstab": {"vorhanden": "ja", "wert": "1:100"},
            "nordpfeil": {"vorhanden": "nein"},
        },
    },
    "p2": {
        "plantyp": "Katasterplan",
        "merkmale": {"massstab": {"vorhanden": "ja", "wert": "1:500"}},
    },
}


class OracleClient:
    """Antwortet je Bild (= Seite) mit der Annotation, ausser `overrides` greift."""

    def __init__(self, overrides: Mapping[tuple[str, str], dict[str, Any]] | None = None):
        self.overrides = overrides or {}

    def complete(
        self, *, question: str, schema: Any, image: bytes | None, image_mime: str, text: str | None
    ) -> RawCompletion:
        assert image is not None
        page = image.decode()
        truth = PAGES[page]
        if question == classify.load_prompt():
            key = "plantyp"
            answer: dict[str, Any] = {"plantyp": truth["plantyp"], "konfidenz": 0.99}
        else:
            key = next(
                n for n in merkmale._config()["merkmale"] if question == merkmale.load_prompt(n)
            )
            ann = truth["merkmale"].get(key, {"vorhanden": "nein"})
            answer = {"vorhanden": ann["vorhanden"]}
            if "wert" in schema["properties"]:
                answer["wert"] = ann.get("wert")
        answer = self.overrides.get((page, key), answer)
        return RawCompletion(text=json.dumps(answer), model="oracle")


def write_set(directory: Path, pages: Mapping[str, Any] = PAGES) -> None:
    entries = []
    for pid, truth in pages.items():
        (directory / f"{pid}.png").write_bytes(pid.encode())
        entries.append({"id": pid, "bild": f"{pid}.png", **truth})
    (directory / "set.json").write_text(json.dumps({"seiten": entries}), encoding="utf-8")


@pytest.fixture
def data(tmp_path: Path) -> Path:
    write_set(tmp_path)
    return tmp_path


def test_perfect_model_passes_all_gates(data: Path) -> None:
    result = evaluate(load_seiten(data), model="oracle", client=OracleClient())
    assert result.passed
    assert result.plantyp == 1.0
    assert result.merkmale == 1.0
    assert result.falsch_erfuellt == []
    assert result.checks["massstab"].total == 2
    assert result.checks["nordpfeil"].total == 1


def test_false_erfuellt_when_feature_missing_fails_gate(data: Path) -> None:
    client = OracleClient({("p1", "nordpfeil"): {"vorhanden": "ja"}})
    result = evaluate(load_seiten(data), model="oracle", client=client)
    assert result.falsch_erfuellt == ["p1:nordpfeil"]
    assert not result.passed
    assert result.gates()["falsch_erfuellt"] is False


def test_unsicher_is_wrong_but_not_false_erfuellt(data: Path) -> None:
    client = OracleClient({("p1", "nordpfeil"): {"vorhanden": "unklar"}})
    result = evaluate(load_seiten(data), model="oracle", client=client)
    assert result.falsch_erfuellt == []
    assert result.checks["nordpfeil"].richtig == 0
    assert result.merkmale < 1.0


def test_wrong_wert_counts_against_accuracy(data: Path) -> None:
    client = OracleClient({("p2", "massstab"): {"vorhanden": "ja", "wert": "1:200"}})
    result = evaluate(load_seiten(data), model="oracle", client=client)
    assert result.checks["massstab"].richtig == 1
    assert result.falsch_erfuellt == []


def test_wrong_plantyp_to_real_type_is_false_erfuellt(data: Path) -> None:
    client = OracleClient({("p2", "plantyp"): {"plantyp": "Schnitt", "konfidenz": 0.99}})
    result = evaluate(load_seiten(data), model="oracle", client=client)
    assert "p2:plantyp" in result.falsch_erfuellt
    assert result.plantyp == 0.5
    assert not result.passed


def test_report_contains_accuracy_per_check_and_model(data: Path) -> None:
    result = evaluate(load_seiten(data), model="oracle", client=OracleClient())
    js = to_json(result)
    assert js["model"] == "oracle"
    assert js["genauigkeit"]["pro_pruefung"]["massstab"]["genauigkeit"] == 1.0
    assert js["bestanden"] is True
    md = to_markdown(result)
    assert "`oracle`" in md and "| massstab | 2 | 2 | 100.0% |" in md


def test_empty_or_broken_set_is_error(tmp_path: Path) -> None:
    with pytest.raises(DataError):
        load_seiten(tmp_path)
    (tmp_path / "x.json").write_text('{"seiten": [{"id": "a"}]}', encoding="utf-8")
    with pytest.raises(DataError):
        load_seiten(tmp_path)


def test_cli_writes_reports_and_exit_code(data: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    code = run.main(
        ["--model", "a/b", "--data", str(data), "--out", str(out)], client=OracleClient()
    )
    assert code == 0
    assert json.loads((out / "a_b.json").read_text())["bestanden"] is True
    assert (out / "a_b.md").exists()

    bad = OracleClient({("p1", "nordpfeil"): {"vorhanden": "ja"}})
    assert run.main(["--model", "m", "--data", str(data), "--out", str(out)], client=bad) == 1


def test_cli_invalid_data_exits_2(tmp_path: Path) -> None:
    assert run.main(["--model", "m", "--data", str(tmp_path), "--out", str(tmp_path)]) == 2
