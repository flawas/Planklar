"""PDF-Export des Berichts mit WeasyPrint aus demselben Template-Baum wie die Web-Ansicht."""

from collections.abc import Mapping
from typing import Any

from jinja2 import Environment
from weasyprint import HTML  # type: ignore[import-untyped]


def _kein_abruf(url: str, *args: Any, **kwargs: Any) -> Any:
    """Der Bericht lädt nichts nach (kein SSRF, keine externen Inhalte)."""
    raise ValueError("Externe Ressourcen sind im Bericht nicht erlaubt")


def render_pdf(env: Environment, context: Mapping[str, Any]) -> bytes:
    html = env.get_template("bericht_pdf.html").render(**{**context, "modus": "pdf"})
    data: bytes = HTML(string=html, url_fetcher=_kein_abruf).write_pdf()
    return data
