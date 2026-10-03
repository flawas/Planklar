from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_multi_stage_on_python_slim() -> None:
    assert DOCKERFILE.count("FROM python:3.12-slim") >= 2


def test_runs_as_non_root() -> None:
    assert "USER planklar" in DOCKERFILE


def test_runtime_has_ocr_and_weasyprint_libs() -> None:
    for pkg in ("tesseract-ocr", "tesseract-ocr-deu", "libpango-1.0-0", "libharfbuzz0b"):
        assert pkg in DOCKERFILE


def test_rules_copied_into_image() -> None:
    assert "COPY --chown=planklar:planklar rules ./rules" in DOCKERFILE
    assert (ROOT / "rules").is_dir()


def test_dockerignore_excludes_secrets_and_vcs() -> None:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert {".git", ".env"} <= set(lines)
