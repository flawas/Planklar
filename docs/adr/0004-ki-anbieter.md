# 0004 – KI-Anbieter und Modell

Status: **Entwurf** (Issue #58, `needs-human`). Die Entscheidung steht aus, bis die Evaluation gelaufen ist und die Verträge geprüft sind.

## Kontext
Der Plan verlangt einen Anbieter mit vertraglich zugesicherter Datenverarbeitung in der Schweiz oder EU und ohne Training auf Kundendaten. Es gehen nur einzelne Seiten/Kacheln an das Modell, nie ganze Dossiers. Die Anbindung läuft über LiteLLM (`LLM_MODEL`, `LLM_API_KEY`); ein Wechsel ändert keinen Code. Der Entwicklungsbetrieb nutzt den Fake-Client, nur der produktive Betrieb ist blockiert.

Kandidaten: Anthropic Claude und OpenAI (ChatGPT-Modelle).

## Vergleich (Stand Recherche 2026-10-04, vor Vertragsabschluss selbst prüfen)

| Kriterium | Anthropic Claude | OpenAI |
|---|---|---|
| Kein Training auf API-Daten | Ja, per Commercial Terms | Ja, Standard bei der API |
| Datenstandort EU/CH | Direkte API: kein EU-Residency; EU-Regionen über AWS Bedrock (Frankfurt, Irland, Paris) oder Google Vertex AI | Europe-Region (EWR und Schweiz) über `eu.api.openai.com`; nur für neue Projekte, setzt Freigabe und Zero-Data-Retention-Zusatz voraus |
| Zero Data Retention | Auf Anfrage (Enterprise); sonst Löschung nach bis zu 30 Tagen | In der EU-Region mit ZDR-Zusatz |
| AVV/DPA | DPA mit SCC | DPA (AVV nach Art. 28 DSGVO) |
| Kosten pro Dossier | offen, aus Evaluation und Preisliste berechnen | offen, aus Evaluation und Preisliste berechnen |

Quellen: [Anthropic API und GDPR](https://compound.law/en-DE/tools/anthropic-api/), [Claude EU Data Residency](https://sonomos.ai/blog/claude-eu-data-residency-2026/), [OpenAI: Data residency in Europe](https://openai.com/index/introducing-data-residency-in-europe/), [OpenAI API GDPR/DPA](https://compound.law/en-DE/tools/openai-api/). Das sind Sekundärquellen; massgebend sind die Verträge der Anbieter.

## Vorgehen bis zur Entscheidung
1. Evaluation beider Modelle: `python -m eval.run --model <litellm-name>` auf dem Set `eval/data/` (10 synthetische Seiten, erzeugt mit `python -m eval.make_synthetic_set`). Gates: Plantyp ≥ 95 %, Merkmale ≥ 90 %, falsche «erfüllt» = 0.
2. Kosten pro Dossier: Tokens pro Seite aus dem Lauf mal typische Seitenzahl, mit aktueller Preisliste.
3. Datenstandort klären: Claude nur über Bedrock/Vertex in einer EU-Region, OpenAI über das EU-Projekt mit ZDR. Beides ist über LiteLLM konfigurierbar (z. B. `bedrock/eu.anthropic...`).
4. DPA abschliessen, beide als Unterauftragsverarbeiter in den AVV mit den Büros aufnehmen.

## Ergebnisse der Evaluation
_Noch offen._ Berichte landen in `eval/reports/`.

| Modell | Plantyp | Merkmale | falsche «erfüllt» | Kosten/Dossier |
|---|---|---|---|---|
| | | | | |

## Entscheidung
_Offen._

## Konsequenzen
- Modellwechsel bleibt Konfiguration; jeder Prüflauf speichert die Modellversion.
- Ein Modellwechsel braucht einen erneuten Evaluationslauf.
