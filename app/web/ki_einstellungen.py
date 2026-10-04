"""Hilfen für die KI-Einstellungen im GUI (Validierung und Verbindungstest)."""

from app.pipeline.llm import LLMError, ask

MSG_MODELL = "Bitte geben Sie ein Modell an, z. B. anthropic/claude-sonnet-5-5."
MSG_BASE = "Der Endpunkt muss mit https:// beginnen."
MSG_TEST_OK = "Verbindung erfolgreich."
MSG_TEST_FEHLER = "Verbindung fehlgeschlagen. Modell, Endpunkt und Schlüssel prüfen."
MSG_TEST_KEIN_MODELL = "Zuerst ein Modell speichern."

# Vorschläge im Eingabefeld; frei überschreibbar (LiteLLM-Modellnamen)
MODELL_VORSCHLAEGE = [
    "anthropic/claude-sonnet-5-5",
    "anthropic/claude-opus-5-5",
    "bedrock/eu.anthropic.claude-sonnet-5-5",
    "openai/gpt-4o",
]

_TEST_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def validiere(modell: str, api_base: str) -> dict[str, str]:
    fehler: dict[str, str] = {}
    if not modell:
        fehler["modell"] = MSG_MODELL
    if api_base and not api_base.startswith("https://"):
        fehler["api_base"] = MSG_BASE
    return fehler


def verbindung_testen() -> tuple[bool, str]:
    """Stellt eine harmlose Testfrage ohne Dokumentinhalt, ohne Fehlerdetails."""
    try:
        ask('Antworte mit {"ok": true}.', _TEST_SCHEMA, text="Verbindungstest")
    except LLMError as exc:
        # Die Meldung enthält nur den Ausnahme-Typ (z. B. AuthenticationError), keine Inhalte.
        return False, f"{MSG_TEST_FEHLER} ({exc})"
    return True, MSG_TEST_OK
