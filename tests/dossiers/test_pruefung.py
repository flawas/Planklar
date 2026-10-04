"""Integrationstest des Prüflaufs: synthetisches Dossier, Fake-LLM, echte DB, Fake-S3."""

import uuid
from collections.abc import Mapping
from typing import Any

import pymupdf
import pytest
from sqlalchemy.orm import Session

from app.db.models import Buero, Dossier, Ergebnis, Kanton, Pruefstatus, Vorhabenstyp
from app.dossiers import pruefung as lauf
from app.dossiers.scope import BueroScope
from app.dossiers.service import upload_dokument
from app.pipeline.llm import LLMError, RawCompletion
from app.storage import Storage
from app.worker import celery_app, run_pruefung_task

FLAGS = {
    "gewaesserbezug": False,
    "kantonsstrassenbezug": False,
    "waldbezug": False,
    "ausserhalb_bauzone": False,
}


class FakeMerkmalClient:
    """Beantwortet jede Merkmalsfrage zustimmend, passend zum Schema (ohne Netz)."""

    model = "fake-model-1"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def complete(
        self,
        *,
        question: str,
        schema: Mapping[str, Any],
        image: bytes | None,
        image_mime: str,
        text: str | None,
    ) -> RawCompletion:
        if self.fail:
            raise LLMError("Modell nicht erreichbar")
        antwort: dict[str, Any] = {"vorhanden": "ja"}
        if "wert" in schema["properties"]:
            antwort["wert"] = "1:100"
        import json

        return RawCompletion(json.dumps(antwort), self.model)


def _pdf(*texte: str) -> bytes:
    doc = pymupdf.open()
    for t in texte:
        doc.new_page().insert_text((72, 72), t)
    data: bytes = doc.tobytes()
    doc.close()
    return data


def _dossier(
    db: Session, storage: Storage, attribute: dict[str, Any] | None = None
) -> tuple[BueroScope, Dossier]:
    buero = Buero(name="Büro Test")
    db.add(buero)
    db.flush()
    scope = BueroScope(db, buero.id)
    dossier = scope.add_dossier(
        kanton=Kanton.LU,
        gemeinde="Luzern",
        vorhabenstyp=Vorhabenstyp.UMBAU_ANBAU,
        attribute=FLAGS if attribute is None else attribute,
    )
    db.commit()
    upload_dokument(
        db, storage, dossier, "plaene.pdf", _pdf("Situationsplan 1:500", "Grundriss EG"), 10**8
    )
    return scope, dossier


def _ergebnisse(scope: BueroScope, pruefung_id: uuid.UUID) -> dict[str, Ergebnis]:
    return {b.regel_id: b.ergebnis for b in scope.list_befunde(pruefung_id)}


def test_pruefung_speichert_seiten_und_befunde(db: Session, storage: Storage) -> None:
    scope, dossier = _dossier(db, storage)
    pruefung = lauf.start_pruefung(scope, dossier.id)
    db.commit()
    assert lauf.fortschritt(scope, pruefung.id).seiten_fertig == 0

    result = lauf.run_pruefung(scope, storage, pruefung.id, client=FakeMerkmalClient())

    assert result.status is Pruefstatus.ABGESCHLOSSEN
    assert result.modellversion == "fake-model-1"
    assert result.beendet_am is not None
    fort = lauf.fortschritt(scope, pruefung.id)
    assert (fort.seiten_gesamt, fort.seiten_fertig) == (2, 2)

    seiten = scope.list_seiten(scope.list_dokumente(dossier.id)[0].id)
    assert [s.plantyp for s in seiten] == ["Situationsplan", "Grundriss"]
    assert seiten[0].merkmale["massstab"]["status"] == "sicher"

    ergebnisse = _ergebnisse(scope, pruefung.id)
    assert ergebnisse["LU-PBV55-2a-situationsplan"] is Ergebnis.ERFUELLT
    assert ergebnisse["LU-PBV55-2b-grundriss"] is Ergebnis.ERFUELLT
    assert ergebnisse["LU-PBV55-1-baugesuchsformular"] is Ergebnis.FEHLT
    assert ergebnisse["LU-PBV56-1-unterschriftenblatt"] is Ergebnis.MANUELL
    # Belege verweisen auf die Seite
    beleg = next(b for b in scope.list_befunde(pruefung.id) if b.regel_id.endswith("grundriss"))
    assert beleg.belege == [str(seiten[1].id)]


def test_wiederholung_ist_idempotent(db: Session, storage: Storage) -> None:
    scope, dossier = _dossier(db, storage)
    pruefung = lauf.start_pruefung(scope, dossier.id)
    db.commit()
    lauf.run_pruefung(scope, storage, pruefung.id, client=FakeMerkmalClient())
    erster = _ergebnisse(scope, pruefung.id)
    lauf.run_pruefung(scope, storage, pruefung.id, client=FakeMerkmalClient())

    assert _ergebnisse(scope, pruefung.id) == erster
    assert len(scope.list_befunde(pruefung.id)) == len(erster)
    assert len(scope.list_seiten(scope.list_dokumente(dossier.id)[0].id)) == 2
    assert len(scope.list_pruefungen(dossier.id)) == 1
    assert lauf.fortschritt(scope, pruefung.id).seiten_fertig == 2


def test_modellfehler_einer_seite_ergibt_unsicher_mit_fehlercode(
    db: Session, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope, dossier = _dossier(db, storage)
    pruefung = lauf.start_pruefung(scope, dossier.id)
    db.commit()
    echt = lauf.extract_merkmale

    def flaky(plantyp: Any, image: bytes, **kw: Any) -> dict[str, Any]:
        if plantyp == "Grundriss":
            raise LLMError("kaputt")
        return echt(plantyp, image, **kw)

    monkeypatch.setattr(lauf, "extract_merkmale", flaky)
    result = lauf.run_pruefung(scope, storage, pruefung.id, client=FakeMerkmalClient())

    assert result.status is Pruefstatus.ABGESCHLOSSEN  # Lauf nicht gestoppt
    seiten = scope.list_seiten(scope.list_dokumente(dossier.id)[0].id)
    assert seiten[0].merkmale["massstab"]["status"] == "sicher"
    assert seiten[1].merkmale == {"_fehler": lauf.FEHLER_MERKMALE}
    assert lauf.fortschritt(scope, pruefung.id).seiten_fertig == 2


def test_unlesbares_dokument_ergibt_unsicher_statt_abbruch(db: Session, storage: Storage) -> None:
    scope, dossier = _dossier(db, storage)
    dokument = scope.list_dokumente(dossier.id)[0]
    storage.delete(dossier.buero_id, dossier.id, dokument.sha256)
    pruefung = lauf.start_pruefung(scope, dossier.id)
    db.commit()

    result = lauf.run_pruefung(scope, storage, pruefung.id, client=FakeMerkmalClient())

    assert result.status is Pruefstatus.ABGESCHLOSSEN
    assert {s.merkmale["_fehler"] for s in scope.list_seiten(dokument.id)} == {lauf.FEHLER_DOKUMENT}
    ergebnisse = _ergebnisse(scope, pruefung.id)
    assert ergebnisse["LU-PBV55-2a-situationsplan"] is Ergebnis.UNSICHER
    assert Ergebnis.ERFUELLT not in ergebnisse.values()


def test_ausgefallenes_modell_ergibt_nie_erfuellt_fuer_merkmale(
    db: Session, storage: Storage
) -> None:
    scope, dossier = _dossier(db, storage)
    pruefung = lauf.start_pruefung(scope, dossier.id)
    db.commit()
    lauf.run_pruefung(scope, storage, pruefung.id, client=FakeMerkmalClient(fail=True))
    seiten = scope.list_seiten(scope.list_dokumente(dossier.id)[0].id)
    assert all(s.merkmale["_fehler"] == lauf.FEHLER_MERKMALE for s in seiten)


def test_fehlende_vorhabensattribute_ergeben_unsicher_statt_weglassen(
    db: Session, storage: Storage
) -> None:
    scope, dossier = _dossier(db, storage, attribute={})
    pruefung = lauf.start_pruefung(scope, dossier.id)
    db.commit()
    lauf.run_pruefung(scope, storage, pruefung.id, client=FakeMerkmalClient())
    ergebnisse = _ergebnisse(scope, pruefung.id)
    assert ergebnisse["LU-PBV55-2b-grundriss"] is Ergebnis.ERFUELLT
    assert any(e is Ergebnis.UNSICHER for e in ergebnisse.values())


def test_fremdes_buero_kann_pruefung_nicht_ausfuehren(db: Session, storage: Storage) -> None:
    scope, dossier = _dossier(db, storage)
    pruefung = lauf.start_pruefung(scope, dossier.id)
    anderes = Buero(name="Fremd")
    db.add(anderes)
    db.commit()
    from app.dossiers.scope import NotFoundError

    with pytest.raises(NotFoundError):
        lauf.run_pruefung(BueroScope(db, anderes.id), storage, pruefung.id)


def test_celery_task_fuehrt_lauf_aus(
    db: Session, storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope, dossier = _dossier(db, storage)
    pruefung = lauf.start_pruefung(scope, dossier.id)
    db.commit()
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    monkeypatch.setattr(celery_app.conf, "task_store_eager_result", False)
    monkeypatch.setattr("app.pipeline.llm._default_client_factory", FakeMerkmalClient)
    monkeypatch.setattr("app.dossiers.service.get_storage", lambda: storage)

    status = run_pruefung_task.delay(str(dossier.buero_id), str(pruefung.id)).get()

    assert status == "abgeschlossen"
    db.expire_all()
    assert lauf.fortschritt(scope, pruefung.id).seiten_fertig == 2
