import json

import pytest

from app.pipeline.llm import FakeLLMClient
from app.pipeline.merkmale import (
    _config,
    extract_merkmale,
    load_prompt,
    merkmale_fuer,
    schema_fuer,
)
from app.pipeline.plantyp import Plantyp


def test_every_plantyp_is_mapped_and_every_merkmal_has_prompt() -> None:
    assert set(_config()["plantyp"]) == {t.value for t in Plantyp}
    for names in _config()["plantyp"].values():
        for name in names:
            assert load_prompt(name)
            assert name in _config()["merkmale"]


def test_required_merkmale_covered() -> None:
    used = {n for names in _config()["plantyp"].values() for n in names}
    assert used == {
        "massstab",
        "datum",
        "planverfasser",
        "unterschrift",
        "nordpfeil",
        "legende_farbcodierung",
    }


def test_mapping_per_plantyp() -> None:
    assert "nordpfeil" in merkmale_fuer(Plantyp.SITUATIONSPLAN)
    assert "legende_farbcodierung" in merkmale_fuer("Grundriss")
    assert merkmale_fuer(Plantyp.GRUNDBUCHAUSZUG) == ()

    out = extract_merkmale(
        Plantyp.KATASTERPLAN.value,
        b"png",
        client=FakeLLMClient(
            responses=[{"vorhanden": "ja", "wert": " 1:100 "}] * 3
            + [{"vorhanden": "nein", "wert": None}] * 3,
            model="fake-1",
        ),
    )
    assert out["massstab"]["status"] == "sicher"
    assert out["massstab"]["vorhanden"] == "ja"
    assert out["massstab"]["wert"] == "1:100"
    assert out["massstab"]["einstimmig"] is True
    assert out["massstab"]["prompt"] == "merkmal_massstab_v1"
    assert out["datum"]["vorhanden"] == "nein"
    assert out["_meta"] == {"model": "fake-1", "plantyp": "Katasterplan"}
    json.dumps(out)  # JSONB-tauglich
    assert out["datum"]["wert"] is None


@pytest.mark.parametrize("leer", ["   ", None, ""])
def test_ja_ohne_wert_ist_unsicher(leer: str | None) -> None:
    ja_leer = [{"vorhanden": "ja", "wert": leer}] * 3
    client = FakeLLMClient(
        responses=ja_leer * 3 + [{"vorhanden": "ja"}] * 6,
        model="fake-1",
    )
    out = extract_merkmale(Plantyp.SITUATIONSPLAN, b"png", client=client)
    for name in ("massstab", "datum", "planverfasser"):
        assert out[name]["status"] == "unsicher"
        assert out[name]["vorhanden"] is None
        assert out[name]["wert"] is None
    assert out["unterschrift"]["vorhanden"] == "ja"


def test_split_vote_is_unsicher() -> None:
    client = FakeLLMClient(
        responses=[{"vorhanden": "ja"}, {"vorhanden": "nein"}, {"vorhanden": "unklar"}],
        model="fake-1",
    )
    out = extract_merkmale(Plantyp.BAUGESUCHSFORMULAR, b"png", client=client)
    assert out["unterschrift"]["status"] == "unsicher"
    assert out["unterschrift"]["vorhanden"] is None


def test_one_question_per_call_three_times() -> None:
    client = FakeLLMClient(responses=[{"vorhanden": "ja"}] * 3, model="m")
    extract_merkmale(Plantyp.BAUGESUCHSFORMULAR, b"png", client=client)
    assert len(client.calls) == 3
    assert {c["question"] for c in client.calls} == {load_prompt("unterschrift")}


def test_no_merkmale_no_calls() -> None:
    client = FakeLLMClient(responses=[], model="m")
    out = extract_merkmale(Plantyp.SONSTIGES, b"png", client=client)
    assert out == {"_meta": {"model": None, "plantyp": "Sonstiges"}}
    assert client.calls == []


def test_unknown_plantyp_rejected() -> None:
    with pytest.raises(ValueError):
        merkmale_fuer("Quatsch")


def test_schema_value_required_only_for_text_merkmale() -> None:
    assert "wert" in schema_fuer("massstab")["required"]
    assert schema_fuer("nordpfeil")["required"] == ["vorhanden"]
