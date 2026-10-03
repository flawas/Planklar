import pytest

from app.pipeline.extraction import Befund, extract_feature
from app.pipeline.llm import FakeLLMClient, LLMError

SCHEMA = {
    "type": "object",
    "properties": {"vorhanden": {"type": "string", "enum": ["ja", "nein", "unklar"]}},
    "required": ["vorhanden"],
    "additionalProperties": False,
}


def _run(responses: list) -> tuple:
    client = FakeLLMClient(responses=list(responses), model="fake-7")
    return extract_feature(
        "Ist ein Nordpfeil sichtbar?", SCHEMA, image=b"png", client=client
    ), client


def test_unanimous() -> None:
    result, client = _run([{"vorhanden": "ja"}] * 3)
    assert result.status is Befund.SICHER
    assert result.wert == {"vorhanden": "ja"}
    assert result.einstimmig and result.stimmen == 3
    assert result.model == "fake-7"
    assert len(client.calls) == 3
    assert {c["question"] for c in client.calls} == {"Ist ein Nordpfeil sichtbar?"}


def test_two_to_one_majority_counts() -> None:
    result, _ = _run([{"vorhanden": "ja"}, {"vorhanden": "nein"}, {"vorhanden": "ja"}])
    assert result.status is Befund.SICHER
    assert result.wert == {"vorhanden": "ja"}
    assert result.stimmen == 2 and not result.einstimmig


def test_split_vote_is_unsicher() -> None:
    result, _ = _run([{"vorhanden": "ja"}, {"vorhanden": "nein"}, {"vorhanden": "unklar"}])
    assert result.status is Befund.UNSICHER
    assert result.wert is None


def test_invalid_answer_counts_as_deviation() -> None:
    result, _ = _run([{"vorhanden": "ja"}, "kein json", {"vorhanden": "nein"}])
    assert result.status is Befund.UNSICHER
    assert result.gueltig == 2


def test_invalid_answer_with_two_agreeing_still_majority() -> None:
    result, _ = _run([{"vorhanden": "ja"}, {"vorhanden": "falsch"}, {"vorhanden": "ja"}])
    assert result.status is Befund.SICHER
    assert result.stimmen == 2 and result.gueltig == 2 and not result.einstimmig


def test_all_invalid_is_unsicher() -> None:
    result, _ = _run(["x", "y", {"foo": 1}])
    assert result.status is Befund.UNSICHER
    assert result.gueltig == 0 and result.model is None


def test_transport_error_propagates() -> None:
    client = FakeLLMClient(responses=[])
    with pytest.raises(LLMError):
        extract_feature("Frage", SCHEMA, text="x", client=client)
