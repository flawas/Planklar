import logging
from typing import Any

import pytest

from app.pipeline import llm
from app.pipeline.llm import FakeLLMClient, LLMError, LLMResponseError, ask

SCHEMA = {
    "type": "object",
    "properties": {"vorhanden": {"type": "boolean"}},
    "required": ["vorhanden"],
    "additionalProperties": False,
}


def test_ask_returns_validated_data_and_model_version() -> None:
    client = FakeLLMClient(responses=[{"vorhanden": True}], model="fake-5")
    answer = ask("Ist ein Nordpfeil sichtbar?", SCHEMA, image=b"png", client=client)
    assert answer.data == {"vorhanden": True}
    assert answer.model == "fake-5"
    assert client.calls[0]["image"] == b"png"


def test_ask_accepts_text_input() -> None:
    client = FakeLLMClient(responses=['{"vorhanden": false}'])
    assert ask("Frage", SCHEMA, text="Seitentext", client=client).data == {"vorhanden": False}


def test_schema_violation_raises() -> None:
    client = FakeLLMClient(responses=[{"vorhanden": "ja"}])
    with pytest.raises(LLMResponseError):
        ask("Frage", SCHEMA, text="x", client=client)


def test_non_json_raises() -> None:
    client = FakeLLMClient(responses=["kein json"])
    with pytest.raises(LLMResponseError):
        ask("Frage", SCHEMA, text="x", client=client)


def test_error_message_does_not_leak_content() -> None:
    client = FakeLLMClient(responses=[{"vorhanden": "GEHEIMER-INHALT"}])
    with pytest.raises(LLMResponseError) as info:
        ask("Frage", SCHEMA, text="x", client=client)
    assert "GEHEIMER-INHALT" not in str(info.value)


def test_exactly_one_input_required() -> None:
    client = FakeLLMClient(responses=[])
    with pytest.raises(ValueError):
        ask("Frage", SCHEMA, client=client)
    with pytest.raises(ValueError):
        ask("Frage", SCHEMA, image=b"x", text="y", client=client)


def test_only_single_image_allowed() -> None:
    client = FakeLLMClient(responses=[])
    pages: Any = [b"a", b"b"]
    with pytest.raises(TypeError):
        ask("Frage", SCHEMA, image=pages, client=client)


def test_invalid_schema_raises_value_error() -> None:
    client = FakeLLMClient(responses=[{}])
    with pytest.raises(ValueError):
        ask("Frage", {"type": "unbekannt"}, text="x", client=client)


def test_exhausted_fake_raises() -> None:
    with pytest.raises(LLMError):
        ask("Frage", SCHEMA, text="x", client=FakeLLMClient(responses=[]))


def test_no_content_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client = FakeLLMClient(responses=[{"vorhanden": True}])
    ask("GEHEIME-FRAGE", SCHEMA, text="GEHEIMER-TEXT", client=client)
    assert "GEHEIM" not in caplog.text


def test_litellm_client_uses_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    import litellm

    from app.config import get_settings

    monkeypatch.setenv("LLM_MODEL", "provider/test-model")
    get_settings.cache_clear()
    seen: dict[str, Any] = {}

    class _Msg:
        content = '{"vorhanden": true}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        model = "provider/test-model-2026"

    def fake_completion(**kwargs: Any) -> _Resp:
        seen.update(kwargs)
        return _Resp()

    monkeypatch.setattr(litellm, "completion", fake_completion)
    try:
        answer = ask("Frage", SCHEMA, image=b"png", client=llm.LiteLLMClient())
    finally:
        get_settings.cache_clear()
    assert seen["model"] == "provider/test-model"
    assert answer.model == "provider/test-model-2026"


def test_litellm_client_requires_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("LLM_MODEL", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(llm.LLMConfigError):
            ask("Frage", SCHEMA, text="x", client=llm.LiteLLMClient())
    finally:
        get_settings.cache_clear()


def test_fake_modell_liefert_schemakonforme_antworten(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings
    from app.pipeline.classify import VISION_SCHEMA
    from app.pipeline.merkmale import schema_fuer

    monkeypatch.setenv("LLM_MODEL", "fake")
    monkeypatch.setenv("ALLOW_FAKE_LLM", "true")
    get_settings.cache_clear()
    try:
        klass = ask("Frage", VISION_SCHEMA, image=b"png")
        assert klass.data["plantyp"] == "Sonstiges" and klass.model == "fake"
        merkmal = ask("Frage", schema_fuer("massstab"), image=b"png")
        assert merkmal.data["vorhanden"] == "ja"
    finally:
        get_settings.cache_clear()


def test_fake_modell_ohne_opt_in_wird_abgelehnt(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("LLM_MODEL", "fake")
    monkeypatch.delenv("ALLOW_FAKE_LLM", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(llm.LLMConfigError):
            ask("Frage", SCHEMA, text="x", client=llm.LiteLLMClient())
    finally:
        get_settings.cache_clear()
