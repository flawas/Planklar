"""End-to-End im Compose-Stack: synthetisches Dossier durch die ganze Pipeline mit Fake-LLM.

Läuft nur mit `E2E_BASE_URL` (siehe `.github/workflows/e2e.yml`), nie im normalen `pytest`-Lauf.
Der Benutzer wird vorher per `python -m app.auth.seed` angelegt (E2E_EMAIL / E2E_PASSWORD).
"""

import os
import re
import time

import httpx
import pymupdf
import pytest

BASE = os.environ.get("E2E_BASE_URL", "")
pytestmark = pytest.mark.skipif(
    not BASE, reason="E2E_BASE_URL nicht gesetzt (nur im Compose-Stack)"
)

SEITEN = ("Baugesuchsformular", "Situationsplan", "Grundriss", "Fassade", "Schnitt")


def _pdf() -> bytes:
    doc = pymupdf.open()
    for titel in SEITEN:
        doc.new_page().insert_text((72, 72), f"{titel} Massstab 1:100 synthetisch")
    data: bytes = doc.tobytes()
    doc.close()
    return data


def test_dossier_durch_die_pipeline_mit_bericht_und_pdf() -> None:
    with httpx.Client(base_url=BASE, timeout=30) as client:
        r = client.post(
            "/auth/login",
            data={
                "username": os.environ["E2E_EMAIL"],
                "password": os.environ["E2E_PASSWORD"],
            },
        )
        assert r.status_code == 204

        dossier = client.post(
            "/dossiers",
            json={
                "kanton": "LU",
                "gemeinde": "Luzern",
                "vorhabenstyp": "neubau_efh_mfh",
                "attribute": {
                    "gewaesserbezug": False,
                    "kantonsstrassenbezug": False,
                    "waldbezug": False,
                    "ausserhalb_bauzone": False,
                },
            },
        ).json()["id"]
        up = client.post(
            f"/dossiers/{dossier}/dokumente",
            files={"file": ("e2e.pdf", _pdf(), "application/pdf")},
        )
        assert up.status_code == 201

        pruefung = client.post(f"/dossiers/{dossier}/pruefungen")
        assert pruefung.status_code == 202
        pid = pruefung.json()["id"]
        url = f"/dossiers/{dossier}/pruefungen/{pid}"

        status = ""
        for _ in range(90):  # bis zu 3 Minuten
            status = client.get(url).json()["status"]
            if status != "laeuft":
                break
            time.sleep(2)
        assert status == "abgeschlossen"

        befunde = client.get(f"{url}/befunde").json()
        assert befunde
        assert {b["ergebnis"] for b in befunde} <= {"erfüllt", "fehlt", "unsicher", "manuell"}

        html = client.get(f"{url}/bericht").text
        assert "Das Tool gibt Hinweise und entscheidet nichts." in html
        assert "PBV LU" in html
        vorschau = re.search(r'src="(/vorschau/[^"]+)"', html)
        if vorschau:
            assert client.get(vorschau.group(1)).content.startswith(b"\x89PNG")

        pdf = client.get(f"{url}/bericht.pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        text = " ".join(p.get_text() for p in pymupdf.open(stream=pdf.content, filetype="pdf"))
        assert "PBV LU" in text
