"""Lädt rules/<Kanton>/kanton.yaml und rules/<Kanton>/gemeinden/*.yaml in Modelle."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.rules.models import Kanton, KantonsRegeln, Regel

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "rules"


class RegelLadeFehler(Exception):
    """Ladefehler mit Datei und, soweit bekannt, Regel-ID."""

    def __init__(self, path: Path, message: str, regel_id: str | None = None) -> None:
        self.path = path
        self.regel_id = regel_id
        self.message = message
        wo = f"{path}" if regel_id is None else f"{path} (Regel '{regel_id}')"
        super().__init__(f"{wo}: {message}")


def _format_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or '<regel>'}: {err['msg']}" for err in exc.errors()
    )


def load_file(path: Path, kanton: Kanton, *, gemeinde_datei: bool = False) -> tuple[Regel, ...]:
    """Lädt eine Regeldatei und prüft, dass der Scope zur Ablage passt.

    Kantonsdatei: keine `gemeinde`. Gemeindedatei: alle Regeln gleiche `gemeinde`.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RegelLadeFehler(path, f"ungültiges YAML: {exc}") from exc
    if not isinstance(data, list):
        raise RegelLadeFehler(path, "Regeldatei muss eine Liste von Regeln sein")

    regeln: list[Regel] = []
    seen: set[str] = set()
    for index, raw in enumerate(data):
        raw_id = raw.get("id") if isinstance(raw, dict) else None
        regel_id = raw_id if isinstance(raw_id, str) else None
        try:
            regel = Regel.model_validate(raw)
        except ValidationError as exc:
            msg = _format_validation_error(exc)
            if regel_id is None:
                msg = f"Eintrag {index + 1}: {msg}"
            raise RegelLadeFehler(path, msg, regel_id) from exc
        if regel.scope.kanton != kanton:
            raise RegelLadeFehler(
                path, f"scope.kanton '{regel.scope.kanton}' passt nicht zu {kanton}", regel.id
            )
        if not gemeinde_datei and regel.scope.gemeinde is not None:
            raise RegelLadeFehler(path, "kanton.yaml darf keine scope.gemeinde setzen", regel.id)
        if gemeinde_datei and regel.scope.gemeinde is None:
            raise RegelLadeFehler(path, "Gemeindedatei braucht scope.gemeinde", regel.id)
        if regeln and regel.scope.gemeinde != regeln[0].scope.gemeinde:
            raise RegelLadeFehler(path, "mehrere Gemeinden in einer Datei", regel.id)
        if regel.id in seen:
            raise RegelLadeFehler(path, "doppelte id in derselben Datei", regel.id)
        seen.add(regel.id)
        regeln.append(regel)
    return tuple(regeln)


def load_kanton(root: Path, kanton: Kanton) -> KantonsRegeln:
    """Lädt `kanton.yaml` (Pflicht) und alle `gemeinden/*.yaml` eines Kantons."""
    basis_path = root / kanton.value / "kanton.yaml"
    if not basis_path.is_file():
        raise RegelLadeFehler(basis_path, "kanton.yaml fehlt")
    basis = load_file(basis_path, kanton)

    gemeinden: dict[str, tuple[Regel, ...]] = {}
    gemeinde_dir = root / kanton.value / "gemeinden"
    paths = sorted(gemeinde_dir.glob("*.yaml")) if gemeinde_dir.is_dir() else []
    for path in paths:
        regeln = load_file(path, kanton, gemeinde_datei=True)
        if not regeln:
            continue
        name = regeln[0].scope.gemeinde
        assert name is not None
        if name in gemeinden:
            raise RegelLadeFehler(path, f"Gemeinde '{name}' ist bereits in einer anderen Datei")
        gemeinden[name] = regeln
    return KantonsRegeln(kanton=kanton, basis=basis, gemeinden=gemeinden)


def load_catalog(root: Path = DEFAULT_ROOT) -> dict[Kanton, KantonsRegeln]:
    """Lädt alle Kantone, deren Verzeichnis unter `root` existiert."""
    return {k: load_kanton(root, k) for k in Kanton if (root / k.value).is_dir()}
