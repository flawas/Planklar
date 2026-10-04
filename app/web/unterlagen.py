"""Anzeige der erwarteten Unterlagen: Regeln aus `app.dossiers.erwartung`, rein informativ."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.db.models import Dokument, Dossier
from app.dossiers.erwartung import ErwarteteUnterlage, erwartete_unterlagen
from app.rules.loader import DEFAULT_ROOT


@dataclass
class UnterlagenZeile:
    unterlage: ErwarteteUnterlage
    # Hochgeladene Dokumente mit Seiten des passenden Plantyps: (Dateiname, Seitenzahlen)
    funde: list[tuple[str, list[int]]] = field(default_factory=list)


def katalog_vorhanden(dossier: Dossier) -> bool:
    return (DEFAULT_ROOT / dossier.kanton.value / "kanton.yaml").is_file()


def unterlagen_zeilen(
    dossier: Dossier, dokumente: Sequence[Dokument]
) -> list[UnterlagenZeile] | None:
    """Erwartete Unterlagen mit Hinweis auf bereits klassifizierte Seiten.

    Die Verknüpfung ist ein Hinweis und keine Prüfung: Ob eine Unterlage erfüllt ist,
    entscheidet allein die Regel-Engine im Prüflauf.
    """
    if not katalog_vorhanden(dossier):
        return None  # Kanton noch ohne Regelkatalog (z. B. Schwyz)
    zeilen = []
    for u in erwartete_unterlagen(dossier).unterlagen:
        funde = []
        for dok in dokumente:
            seiten = [s.nummer for s in dok.seiten if s.plantyp == u.dokument]
            if seiten:
                funde.append((dok.dateiname, seiten))
        zeilen.append(UnterlagenZeile(u, funde))
    return zeilen
