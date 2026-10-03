import json
from pathlib import Path

from app.rules import source_check

ROOT = Path(__file__).resolve().parents[2]
RULE = """
- id: {id}
  quelle: {{ erlass: X, paragraph: "§ 1", url: "{url}" }}
"""


def _rules(tmp_path: Path) -> Path:
    d = tmp_path / "rules"
    d.mkdir()
    (d / "a.yaml").write_text(
        RULE.format(id="A", url="https://x.ch/a") + RULE.format(id="B", url="https://x.ch/a")
    )
    (d / "b.yaml").write_text(RULE.format(id="C", url="https://x.ch/c"))
    return d


def test_collect_urls_dedupes(tmp_path: Path) -> None:
    assert source_check.collect_urls(_rules(tmp_path)) == {
        "https://x.ch/a": ["A", "B"],
        "https://x.ch/c": ["C"],
    }


def test_real_catalog_has_urls() -> None:
    assert source_check.collect_urls(ROOT / "rules")


def _run(
    tmp_path: Path, stored: dict[str, str] | None, fetcher: source_check.Fetcher, *extra: str
) -> int:
    rules = _rules(tmp_path)
    hashes = tmp_path / "h.json"
    if stored is not None:
        hashes.write_text(json.dumps(stored))
    return source_check.main(
        [
            "--rules-dir",
            str(rules),
            "--hash-file",
            str(hashes),
            "--report",
            str(tmp_path / "r.md"),
            *extra,
        ],
        fetcher,
    )


def _sha(b: bytes) -> str:
    import hashlib

    return hashlib.sha256(b).hexdigest()


def test_unchanged_exits_zero(tmp_path: Path) -> None:
    stored = {"https://x.ch/a": _sha(b"1"), "https://x.ch/c": _sha(b"1")}
    assert _run(tmp_path, stored, lambda u: b"1") == 0
    assert not (tmp_path / "r.md").exists()


def test_change_reported_without_touching_rules(tmp_path: Path) -> None:
    stored = {"https://x.ch/a": _sha(b"old"), "https://x.ch/c": _sha(b"1")}
    assert _run(tmp_path, stored, lambda u: b"1") == 1
    report = (tmp_path / "r.md").read_text()
    assert "https://x.ch/a" in report and "A, B" in report
    assert json.loads((tmp_path / "h.json").read_text()) == stored


def test_fetch_error_and_missing_reference_reported(tmp_path: Path) -> None:
    def fetcher(url: str) -> bytes:
        if url.endswith("/c"):
            raise TimeoutError
        return b"1"

    assert _run(tmp_path, None, fetcher) == 1
    report = (tmp_path / "r.md").read_text()
    assert "Abruf fehlgeschlagen" in report and "Kein gespeicherter Stand" in report


def test_update_writes_hashes(tmp_path: Path) -> None:
    assert _run(tmp_path, None, lambda u: b"1", "--update") == 0
    assert set(json.loads((tmp_path / "h.json").read_text())) == {
        "https://x.ch/a",
        "https://x.ch/c",
    }


def test_update_keeps_stored_hash_of_failed_url(tmp_path: Path) -> None:
    def fetcher(url: str) -> bytes:
        if url.endswith("/a"):
            raise OSError("down")
        return b"1"

    assert _run(tmp_path, {"https://x.ch/a": "alt"}, fetcher, "--update") == 1
    saved = json.loads((tmp_path / "h.json").read_text())
    assert saved["https://x.ch/a"] == "alt"
    assert set(saved) == {"https://x.ch/a", "https://x.ch/c"}


def test_workflow_is_only_network_user() -> None:
    wf = (ROOT / ".github/workflows/rules-source-check.yml").read_text()
    assert "schedule:" in wf and "workflow_dispatch:" in wf
    assert "needs-human" in wf
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "source_check" not in ci
