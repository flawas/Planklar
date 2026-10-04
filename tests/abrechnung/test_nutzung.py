import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.abrechnung.nutzung import monatsauswertung, monatsgrenzen, nutzung_erfassen
from app.db.base import Base
from app.db.models import Buero
from app.dossiers.scope import BueroScope
from app.pipeline import llm
from app.pipeline.llm import FakeLLMClient, Verbrauch, ask, nutzung_senke

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def test_ask_meldet_verbrauch_an_senke() -> None:
    gemeldet: list[tuple[str, str, Verbrauch]] = []
    client = FakeLLMClient(
        [{"ok": True}], model="m-1", verbrauch=Verbrauch(120, 8, Decimal("0.01"))
    )
    with nutzung_senke(lambda *a: gemeldet.append(a)):
        answer = ask("Frage", SCHEMA, text="x", client=client, zweck="merkmal")
    assert gemeldet == [("merkmal", "m-1", Verbrauch(120, 8, Decimal("0.01")))]
    assert answer.verbrauch.input_tokens == 120


def test_ask_meldet_verbrauch_auch_bei_ungueltiger_antwort() -> None:
    gemeldet: list[Any] = []
    client = FakeLLMClient(["kein json"], verbrauch=Verbrauch(50, 5))
    with nutzung_senke(lambda *a: gemeldet.append(a)):
        with pytest.raises(llm.LLMResponseError):
            ask("Frage", SCHEMA, text="x", client=client)
    assert len(gemeldet) == 1


def test_ask_ohne_senke_und_fehlerhafte_senke_brechen_nicht_ab() -> None:
    assert ask("F", SCHEMA, text="x", client=FakeLLMClient([{"ok": True}])).data == {"ok": True}

    def kaputt(*_: Any) -> None:
        raise RuntimeError("GEHEIMER-INHALT")

    with nutzung_senke(kaputt):
        assert ask("F", SCHEMA, text="x", client=FakeLLMClient([{"ok": True}])).data["ok"]


def test_litellm_client_liest_token_und_kosten(monkeypatch: pytest.MonkeyPatch) -> None:
    import litellm

    from app.config import get_settings

    monkeypatch.setenv("LLM_MODEL", "provider/test-model")
    get_settings.cache_clear()

    class _Usage:
        prompt_tokens = 1000
        completion_tokens = 40

    class _Msg:
        content = '{"ok": true}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        model = "provider/test-model"
        usage = _Usage()

    monkeypatch.setattr(litellm, "completion", lambda **_: _Resp())
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.0042)
    try:
        answer = ask("F", SCHEMA, text="x", client=llm.LiteLLMClient())
    finally:
        get_settings.cache_clear()
    assert answer.verbrauch == Verbrauch(1000, 40, Decimal("0.0042"))


def test_unbekannter_preis_ergibt_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import litellm

    def kein_preis(**_: Any) -> float:
        raise ValueError("unbekannt")

    monkeypatch.setattr(litellm, "completion_cost", kein_preis)
    verbrauch = llm._verbrauch(object())
    assert verbrauch == Verbrauch(0, 0, None)


def test_monatsgrenzen() -> None:
    assert monatsgrenzen(date(2026, 10, 17)) == (
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 11, 1, tzinfo=UTC),
    )
    assert monatsgrenzen(date(2026, 12, 1))[1] == datetime(2027, 1, 1, tzinfo=UTC)


@pytest.fixture
def bueros(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    from app.db import session as db_session

    Base.metadata.create_all(engine)
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: lambda: Session(engine))
    monkeypatch.setattr("app.abrechnung.nutzung.get_sessionmaker", lambda: lambda: Session(engine))
    with Session(engine) as s:
        a, b = Buero(name="A"), Buero(name="B")
        s.add_all([a, b])
        s.commit()
        yield a.id, b.id


def test_nutzung_wird_pro_buero_gebucht_und_ausgewertet(
    engine: Engine, bueros: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = bueros
    client = FakeLLMClient(
        [{"ok": True}] * 3, model="m-1", verbrauch=Verbrauch(100, 10, Decimal("0.5"))
    )
    with nutzung_erfassen(a, uuid.uuid4()):
        ask("F", SCHEMA, text="x", client=client, zweck="klassifikation")
        ask("F", SCHEMA, text="x", client=client, zweck="merkmal")
    with nutzung_erfassen(b):
        ask("F", SCHEMA, text="x", client=client)

    heute = datetime.now(UTC).date()
    with Session(engine) as s:
        auswertung = {n.buero: n for n in monatsauswertung(s, heute)}
    assert auswertung["A"].aufrufe == 2
    assert auswertung["A"].input_tokens == 200
    assert auswertung["A"].output_tokens == 20
    assert auswertung["A"].kosten_usd == Decimal("1.0")
    assert auswertung["B"].aufrufe == 1
    assert auswertung["A"].modelle[0].modell == "m-1"

    # anderer Monat: nichts
    with Session(engine) as s:
        assert all(n.aufrufe == 0 for n in monatsauswertung(s, date(2020, 1, 1)))


def test_scope_summen_enthalten_nur_eigenes_buero(
    engine: Engine, bueros: tuple[uuid.UUID, uuid.UUID]
) -> None:
    a, b = bueros
    with nutzung_erfassen(a):
        ask("F", SCHEMA, text="x", client=FakeLLMClient([{"ok": True}], verbrauch=Verbrauch(7, 1)))
    von, bis = monatsgrenzen(datetime.now(UTC).date())
    with Session(engine) as s:
        assert BueroScope(s, b).llm_nutzung_summen(von, bis) == []
        assert len(BueroScope(s, a).llm_nutzung_summen(von, bis)) == 1
