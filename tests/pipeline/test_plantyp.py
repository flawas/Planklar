import pytest

from app.pipeline.plantyp import Plantyp, classify_text


def test_enum_hat_13_typen() -> None:
    assert len(Plantyp) == 13


@pytest.mark.parametrize(
    ("text", "erwartet"),
    [
        ("Neubau EFH\nGrundriss EG\n1:100", Plantyp.GRUNDRISS),
        ("Schnitt A-A\nMst. 1:100", Plantyp.SCHNITT),
        ("Nordfassade 1:100\nFassade Nord", Plantyp.FASSADE_ANSICHT),
        ("Umgebungsplan 1:200", Plantyp.UMGEBUNGSPLAN),
        ("Entwässerungsplan Liegenschaft", Plantyp.ENTWAESSERUNGSPLAN),
        ("Grundbuchauszug Parzelle 123", Plantyp.GRUNDBUCHAUSZUG),
        ("Baubeschrieb Neubau", Plantyp.BAUBESCHRIEB),
        ("Energienachweis EN-101", Plantyp.ENERGIENACHWEIS),
        ("Deklaration Erdbebensicherheit", Plantyp.DEKLARATION_ERDBEBENSICHERHEIT),
        ("Baugesuchsformular Kanton Luzern", Plantyp.BAUGESUCHSFORMULAR),
    ],
)
def test_klare_planköpfe(text: str, erwartet: Plantyp) -> None:
    result = classify_text(text)
    assert result.plantyp is erwartet
    assert result.konfidenz >= 0.8


def test_situation_mit_massstab_hat_hohe_konfidenz() -> None:
    result = classify_text("Situation 1:500")
    assert result.plantyp is Plantyp.SITUATIONSPLAN
    assert result.konfidenz >= 0.8


def test_gross_kleinschreibung_egal() -> None:
    assert classify_text("GRUNDRISS OG").plantyp is Plantyp.GRUNDRISS


def test_mehrdeutiger_text_hat_niedrige_konfidenz() -> None:
    result = classify_text("Grundriss und Schnitt A-A")
    assert result.konfidenz < 0.5
    assert set(result.kandidaten) == {Plantyp.GRUNDRISS, Plantyp.SCHNITT}


def test_ohne_treffer_sonstiges_ohne_konfidenz() -> None:
    result = classify_text("Lorem ipsum")
    assert result.plantyp is Plantyp.SONSTIGES
    assert result.konfidenz == 0.0
    assert classify_text("").konfidenz == 0.0
