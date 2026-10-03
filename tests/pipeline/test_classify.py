from app.pipeline import classify
from app.pipeline.classify import classify_page, classify_vision
from app.pipeline.llm import FakeLLMClient
from app.pipeline.plantyp import Plantyp


def _vote(typ: str, konf: float = 0.9) -> dict[str, object]:
    return {"plantyp": typ, "konfidenz": konf}


def test_confident_heuristic_skips_vision() -> None:
    client = FakeLLMClient(responses=[])
    result = classify_page("Grundriss Erdgeschoss", b"img", client=client)
    assert result.plantyp == Plantyp.GRUNDRISS
    assert client.calls == []


def test_low_confidence_uses_vision() -> None:
    client = FakeLLMClient(responses=[_vote("Schnitt")] * 3)
    result = classify_page("nichts erkennbar", b"img", client=client)
    assert (result.plantyp, result.konfidenz) == (Plantyp.SCHNITT, 0.9)
    assert len(client.calls) == 3
    assert all(c["image"] == b"img" for c in client.calls)
    assert client.calls[0]["schema"] == classify.VISION_SCHEMA


def test_no_image_keeps_heuristic() -> None:
    client = FakeLLMClient(responses=[])
    assert classify_page("nichts", None, client=client).plantyp == Plantyp.SONSTIGES


def test_invalid_response_gives_sonstiges_zero() -> None:
    for bad in ("kein json", _vote("Erfundener Typ"), {"plantyp": "Schnitt"}):
        result = classify_vision(b"img", client=FakeLLMClient(responses=[bad] * 3))
        assert (result.plantyp, result.konfidenz) == (Plantyp.SONSTIGES, 0.0)


def test_disagreement_gives_sonstiges_zero() -> None:
    client = FakeLLMClient(
        responses=[_vote("Schnitt"), _vote("Grundriss"), _vote("Situationsplan")]
    )
    result = classify_vision(b"img", client=client)
    assert (result.plantyp, result.konfidenz) == (Plantyp.SONSTIGES, 0.0)


def test_majority_counts_with_min_confidence() -> None:
    client = FakeLLMClient(
        responses=[_vote("Schnitt", 0.9), _vote("Grundriss", 0.9), _vote("Schnitt", 0.6)]
    )
    result = classify_vision(b"img", client=client)
    assert (result.plantyp, result.konfidenz) == (Plantyp.SCHNITT, 0.6)


def test_prompt_is_versioned_file() -> None:
    assert classify.PROMPT_PATH.name == "klassifikation_vision_v1.txt"
    assert classify.load_prompt()


def test_schema_enum_matches_plantyp() -> None:
    assert set(classify.VISION_SCHEMA["properties"]["plantyp"]["enum"]) == {
        t.value for t in Plantyp
    }
