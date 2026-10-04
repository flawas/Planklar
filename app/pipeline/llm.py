"""LLM-Abstraktion: eine enge Frage pro Aufruf, Antwort gegen JSON-Schema validiert.

Es geht immer nur eine Seite/Kachel (Einzelbild) oder ein Text an das Modell, nie ein
ganzes Dossier. Frage, Bild und Antwort werden nicht geloggt.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import jsonschema

from app.pipeline.llm_config import LLMConfig, load_config


class LLMError(Exception):
    """Basisfehler der LLM-Abstraktion."""


class LLMConfigError(LLMError):
    """Konfiguration unvollständig (z. B. kein Modell gesetzt)."""


class LLMResponseError(LLMError):
    """Antwort ist kein JSON oder verletzt das JSON-Schema."""


@dataclass(frozen=True)
class RawCompletion:
    """Rohantwort eines Clients: Antworttext und tatsächlich verwendete Modellversion."""

    text: str
    model: str


@dataclass(frozen=True)
class Answer:
    """Validierte Antwort samt Modellversion (wird mit dem Ergebnis gespeichert)."""

    data: Any
    model: str


class LLMClient(Protocol):
    def complete(
        self,
        *,
        question: str,
        schema: Mapping[str, Any],
        image: bytes | None,
        image_mime: str,
        text: str | None,
    ) -> RawCompletion: ...


class LiteLLMClient:
    """Produktiver Client über LiteLLM; Konfiguration aus GUI-Einstellungen oder Umgebung.

    `model` überschreibt das konfigurierte Modell (z. B. für Evaluationsläufe) samt Schlüssel.
    """

    def __init__(self, model: str | None = None) -> None:
        self._model = model

    def complete(
        self,
        *,
        question: str,
        schema: Mapping[str, Any],
        image: bytes | None,
        image_mime: str,
        text: str | None,
    ) -> RawCompletion:
        import litellm

        config = load_config()
        if self._model and self._model != config.model:
            # Anderes Modell: Schlüssel/Endpunkt der Konfiguration gehören nicht dazu; LiteLLM
            # nimmt dann die Standard-Variablen des Anbieters (ANTHROPIC_API_KEY, OPENAI_API_KEY).
            config = LLMConfig(self._model, "", "")
        if not config.model:
            raise LLMConfigError("Kein KI-Modell konfiguriert")

        content: list[dict[str, Any]] = [{"type": "text", "text": question}]
        if text is not None:
            content.append({"type": "text", "text": text})
        if image is not None:
            encoded = base64.b64encode(image).decode("ascii")
            url = f"data:{image_mime};base64,{encoded}"
            content.append({"type": "image_url", "image_url": {"url": url}})

        try:
            response = litellm.completion(
                model=config.model,
                api_key=config.api_key or None,
                api_base=config.api_base or None,
                messages=[{"role": "user", "content": content}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "schema": dict(schema), "strict": True},
                },
                temperature=0,
            )
        except Exception as exc:  # Details können Inhalte enthalten, daher nicht durchreichen
            raise LLMError(f"LLM-Aufruf fehlgeschlagen ({type(exc).__name__})") from None

        message = response.choices[0].message.content
        if not isinstance(message, str):
            raise LLMResponseError("Leere Antwort des Modells")
        return RawCompletion(text=message, model=str(response.model or config.model))


@dataclass
class FakeLLMClient:
    """Fake-Client für Tests ohne Netz: liefert aufgezeichnete Antworten der Reihe nach."""

    responses: list[str | Mapping[str, Any]]
    model: str = "fake-model-1"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(
        self,
        *,
        question: str,
        schema: Mapping[str, Any],
        image: bytes | None,
        image_mime: str,
        text: str | None,
    ) -> RawCompletion:
        self.calls.append({"question": question, "schema": schema, "image": image, "text": text})
        if not self.responses:
            raise LLMError("Keine aufgezeichnete Antwort mehr vorhanden")
        recorded = self.responses.pop(0)
        body = recorded if isinstance(recorded, str) else json.dumps(recorded)
        return RawCompletion(text=body, model=self.model)


_default_client_factory: Callable[[], LLMClient] = LiteLLMClient


def ask(
    question: str,
    json_schema: Mapping[str, Any],
    *,
    image: bytes | None = None,
    text: str | None = None,
    image_mime: str = "image/png",
    client: LLMClient | None = None,
) -> Answer:
    """Stellt dem Modell eine enge Frage zu genau einer Seite/Kachel (`image`) oder einem Text.

    `image` ist ein einzelnes Bild (bytes), nie eine Liste oder ein Dossier. Ungültige
    Antworten führen zu `LLMResponseError`; es wird nicht stillschweigend weitergemacht.
    """
    if (image is None) == (text is None):
        raise ValueError("Genau eines von `image` oder `text` angeben")
    if image is not None and not isinstance(image, bytes | bytearray):
        raise TypeError("`image` muss ein einzelnes Bild (bytes) sein")

    try:
        jsonschema.Draft202012Validator.check_schema(json_schema)
    except jsonschema.SchemaError as exc:
        raise ValueError("Ungültiges JSON-Schema") from exc

    llm = client if client is not None else _default_client_factory()
    raw = llm.complete(
        question=question,
        schema=json_schema,
        image=bytes(image) if image is not None else None,
        image_mime=image_mime,
        text=text,
    )

    try:
        data = json.loads(raw.text)
    except json.JSONDecodeError:
        raise LLMResponseError("Antwort ist kein gültiges JSON") from None
    try:
        jsonschema.Draft202012Validator(json_schema).validate(data)
    except jsonschema.ValidationError as exc:
        # Nur Schema-Pfad, nie den Wert (könnte Dokumentinhalt sein)
        path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise LLMResponseError(f"Antwort verletzt das Schema bei {path}") from None
    return Answer(data=data, model=raw.model)
