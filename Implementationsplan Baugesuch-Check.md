# Implementationsplan Baugesuch-Check

Oct 4, 2026 · @Flavio

## Ziel und MVP-Scope

Das MVP ist ein Vorab-Check für Architekt:innen und Planer: Dossier hochladen, Vorhaben beschreiben, Mängelliste erhalten, bevor das Gesuch auf eBAGE+ oder eBau eingereicht wird. Es deckt die Kantone Luzern und Schwyz ab und läuft vollständig als Docker-Compose-Stack.

| Bereich | Im MVP | Später |
| --- | --- | --- |
| Kantone | Luzern, Schwyz | Weitere Inosca-Kantone (BE, SO, UR, GR, AG), dann ZH |
| Gemeinden | 2 pro Kanton (z.B. Stadt Luzern, Weggis, Küssnacht, eine Ausserschwyzer Gemeinde) | Alle Gemeinden über kantonale Basis + Overrides |
| Vorhabenstypen | Neubau EFH/MFH, Umbau/Anbau, Heizungsersatz Wärmepumpe | PV, Reklame, Bauten ausserhalb Bauzone |
| Input | PDFs (Baugesuchsformular, Pläne, Beilagen) | eCH-0211-Import, IFC/BIM |
| Prüftiefe | Formelle Vollständigkeit: Dokumente vorhanden, Plantyp, Pflichtangaben auf Plänen | Plausibilität (Flächen, Abstände) |
| Nutzer | Einzelne Büros, Login pro Büro | Mandantenfähig mit Rollen, Abrechnung |

Nicht im Scope: materielle Baurechtsprüfung (Abstände, Ausnützung, Zonenkonformität). Das Tool gibt Hinweise und entscheidet nichts.

## Architekturüberblick

Der Stack besteht aus sechs Containern: ein eigenes Applikations-Image, das als web und als worker läuft, plus Standard-Images für Proxy, Datenbank, Queue und Dateispeicher. Nur der KI-Aufruf verlässt den Stack.

&#91;embedded content: Architektur · 6 Container plus externer KI-Anbieter\]

Der Web-Container nimmt Uploads an und legt einen Job in die Queue; der Worker verarbeitet ihn, fragt den KI-Anbieter nur mit Seitenausschnitten an und schreibt die Befunde in Postgres.

## Tech-Stack

Python im Kern, weil PDF-Verarbeitung, OCR und KI-Anbindung dort am ausgereiftesten sind. Das Frontend bleibt serverseitig gerendert, damit du als Einzelentwickler nur eine Codebasis pflegst.

| Komponente | Wahl | Begründung |
| --- | --- | --- |
| API und Web-UI | Python 3.12, FastAPI, Jinja2 + HTMX | Ein Service für API und Oberfläche, kein separates JS-Build |
| Hintergrundjobs | Celery mit Redis | Prüfläufe dauern Minuten, gehören nicht in den Request |
| Datenbank | PostgreSQL 16 (JSONB für Regelbedingungen) | Relationale Daten plus flexible Bedingungen in einem System |
| Dateispeicher | MinIO (S3-kompatibel) | Lokal im Container, später austauschbar gegen jeden S3-Speicher |
| PDF-Verarbeitung | PyMuPDF | Rendern, Textlayer und PDF-Formularfelder in einer Bibliothek |
| OCR-Fallback | Tesseract mit Sprachpaket deu | Für gescannte Formulare ohne Textlayer |
| KI-Anbindung | LiteLLM als Abstraktion, Vision-Modell mit strukturiertem JSON-Output | Modell wechselbar, ohne Prüflogik anzufassen |
| Regelauswertung | Eigene Engine, Bedingungen als JSON Logic (json-logic-py) | Deterministisch, testbar, nachvollziehbar |
| Berichte | WeasyPrint (HTML zu PDF) | Ein Template für Web-Ansicht und PDF-Export |
| Authentifizierung | FastAPI-Users (E-Mail/Passwort), OIDC vorbereitet | Später Anbindung an Entra ID oder Keycloak ohne Umbau |
| Reverse Proxy | Caddy | Automatisches TLS, minimale Konfiguration |
| Migrationen und Tests | Alembic, pytest | Standard im FastAPI-Umfeld |

## Datenmodell und Regelkatalog

Der Regelkatalog lebt als YAML in einem eigenen Git-Verzeichnis und wird beim Start in die Datenbank geladen. So ist jede Regeländerung versioniert, reviewbar und in CI gegen ein JSON-Schema validiert.

**Ablage im Repo**

```
rules/
  schema.json
  LU/
    kanton.yaml
    gemeinden/
      luzern.yaml
      weggis.yaml
  SZ/
    kanton.yaml
    gemeinden/
      kuessnacht.yaml
```

**Regel-Schema**

```yaml
- id: SZ-PBV-37-schattendiagramm
  titel: Schattendiagramm bei Hochhäusern
  scope: { kanton: SZ }
  when: { "==": [{ var: gebaeudetyp }, "hochhaus"] }
  requires:
    typ: dokument
    dokument: schattendiagramm
  check: ki_klassifikation
  schwere: fehlt_blockierend
  quelle: { erlass: "PBV SZ", paragraph: "§ 37", url: "..." }
  stand: 2026-02-01
```

**Vererbung:** Die Kantonsdatei ist die Basis. Eine Gemeindedatei kann Regeln ergänzen, per gleicher `id` ersetzen oder mit `disabled: true` ausschalten. Die Engine löst das zur Laufzeit zum effektiven Regelset für Gemeinde und Vorhaben auf.

**Prüfmethoden** (Feld `check`): `ki_klassifikation` (Dokument vorhanden), `formularfeld` (Wert im PDF-Formular), `plan_merkmal` (z.B. Massstab, Nordpfeil auf einem Plantyp), `manuell` (Checkbox für den Planer).

| Entität | Wichtigste Felder |
| --- | --- |
| Regelset | Kanton, Gemeinde, Git-Commit-Hash, geladen am |
| Regel | id, scope, when, requires, check, schwere, quelle, stand |
| Dossier | Büro, Kanton, Gemeinde, Vorhabenstyp, Vorhabens-Attribute (JSONB), Status |
| Dokument | Dossier, Dateiname, SHA-256, Seitenzahl, Speicherpfad |
| Seite | Dokument, Seitennummer, Plantyp, Konfidenz, extrahierte Merkmale (JSONB) |
| Prüflauf | Dossier, Regelset-Hash, Modellversion, Start, Ende |
| Befund | Prüflauf, Regel, Ergebnis (erfüllt, fehlt, unsicher, manuell), Belege (Seiten-IDs), Override mit Begründung |

Jeder Prüflauf speichert Regelset-Hash und Modellversion. Damit ist jeder Bericht später exakt reproduzierbar.

**Quellen für den ersten Regelkatalog**

- Luzern: § 188 PBG, § 55 PBV, rawi-Wegleitung «Baugesuch und Beilagen» (Stand Juli 2023), Deklaration Erdbebensicherheit, Merkblatt Baugesuche der Stadt Luzern
- Schwyz: § 77 PBG, Planungs- und Bauverordnung (SRSZ 400.111), Baureglemente der Pilotgemeinden
- Inosca-Repository (github.com/inosca/ebau): prüfen, ob die Schwyzer Formulardefinitionen maschinenlesbar enthalten sind

## Prüf-Pipeline

Jeder Prüflauf zerlegt das Dossier in viele enge Einzelfragen. Die KI beantwortet nur diese Einzelfragen; ob eine Anforderung erfüllt ist, entscheidet die Regel-Engine. Das folgt der Erkenntnis aus der [Zürcher KI-Sandbox](https://www.zh.ch/de/wirtschaft-arbeit/wirtschaftsstandort/innovation-sandbox/phase-ii/ki-bei-baubewilligungen/potenzialanalyse-und-grenzen-von-ki.html), dass modulare Teilprüfungen zuverlässig sind, eine Gesamtprüfung in einem Schritt nicht.

1. **Vorhaben erfassen:** Assistent fragt Kanton, Gemeinde, Vorhabenstyp, Verfahren und relevante Attribute ab (z.B. Gebäudehöhe, Heizsystem, innerhalb Bauzone). Daraus löst die Engine das effektive Regelset auf und zeigt dem Planer sofort die Liste der erwarteten Unterlagen.
2. **Upload:** PDFs landen in MinIO, mit SHA-256-Hash gegen Doppel-Uploads. Danach startet ein Celery-Job.
3. **Vorverarbeitung:** PyMuPDF zerlegt in Seiten, liest Textlayer und Formularfelder und rendert jede Seite mit 200 dpi. Grossformatige Pläne (A1, A0) werden zusätzlich in überlappende Kacheln geschnitten. Seiten ohne Textlayer gehen durch Tesseract.
4. **Klassifikation:** Erst eine günstige Heuristik über den Text (Planköpfe enthalten oft «Grundriss EG» oder «Situation 1:500»), dann bei Unsicherheit das Vision-Modell. Ergebnis pro Seite: Plantyp aus einer festen Liste plus Konfidenz.
5. **Merkmalsextraktion:** Pro Plantyp gezielte Fragen mit JSON-Schema, z.B. Massstab, Datum, Planverfasser, Unterschrift, Nordpfeil, Legende mit Farbcodierung Neu/Abbruch. Jede Frage läuft dreimal, gewertet wird die Mehrheit; Abweichungen ergeben «unsicher».
6. **Regelauswertung:** Die Engine prüft jede anwendbare Regel gegen Formularfelder und Seitenbefunde und setzt erfüllt, fehlt, unsicher oder manuell, jeweils mit Verweis auf die belegenden Seiten.
7. **Bericht:** Ampel pro Anforderung, Quellenangabe, Vorschau der belegenden Seite. Der Planer kann einen Befund mit Begründung übersteuern; diese Overrides fliessen ins Evaluations-Set zurück. Export als PDF.

Die feste Plantyp-Liste fürs MVP: Baugesuchsformular, Situationsplan, Grundriss, Schnitt, Fassade/Ansicht, Umgebungsplan, Entwässerungsplan, Katasterplan, Grundbuchauszug, Baubeschrieb, Energienachweis, Deklaration Erdbebensicherheit, Sonstiges.

## Phasenplan

Bei rund 8 bis 10 Stunden pro Woche ist ein Pilot nach etwa 22 Wochen realistisch. Luzern kommt zuerst, weil die Wegleitung die bessere Grundlage ist; Schwyz dient danach als Test, ob das Regelschema einen zweiten Kanton ohne Umbau aufnimmt.

&#91;embedded content: Phasenplan · 6 Phasen mit Abnahmekriterien\]

Jede Phase endet mit einem prüfbaren Kriterium. Ist es nicht erreicht, geht es nicht in die nächste Phase, sondern zurück an die Ursache, meist Regelschema oder Prompts.

## Docker-Setup

Ein einziges Applikations-Image dient als Web-Service und als Worker, nur mit anderem Startbefehl. Daneben laufen Standard-Images für Datenbank, Queue, Speicher und Proxy. Alles startet mit `docker compose up -d`.

```yaml
services:
  proxy:
    image: caddy:2
    ports: ["80:80", "443:443"]
    volumes: [./Caddyfile:/etc/caddy/Caddyfile, caddy_data:/data]
  web:
    image: ghcr.io/<owner>/baugesuch-check:${TAG}
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    env_file: .env
    depends_on: [db, redis, minio]
  worker:
    image: ghcr.io/<owner>/baugesuch-check:${TAG}
    command: celery -A app.worker worker --concurrency=2
    env_file: .env
    depends_on: [db, redis, minio]
  db:
    image: postgres:16
    volumes: [pg_data:/var/lib/postgresql/data]
  redis:
    image: redis:7
  minio:
    image: minio/minio
    command: server /data
    volumes: [minio_data:/data]
volumes: { caddy_data: {}, pg_data: {}, minio_data: {} }
```

**Dockerfile:** Multi-Stage auf `python:3.12-slim`. Im Laufzeit-Image zusätzlich `tesseract-ocr` und `tesseract-ocr-deu` sowie die System-Libraries für WeasyPrint. Der Regelkatalog wird ins Image kopiert, damit Image-Tag und Regelstand zusammenpassen; für die Regelpflege lokal per Volume überschreibbar.

**Konfiguration:** Alles über Umgebungsvariablen (`DATABASE_URL`, `S3_ENDPOINT`, `LLM_MODEL`, `LLM_API_KEY`, `RETENTION_DAYS`). Secrets in Produktion als Docker Secrets, nicht in `.env`.

**Start und Betrieb:**

- Web-Container führt beim Start `alembic upgrade head` aus und lädt das Regelset in die Datenbank.
- Healthchecks für web (`/health`), db und redis; `restart: unless-stopped` für alle Services.
- CI (GitHub Actions): Tests, Regel-Schema-Validierung, Image-Build, Push in die GitHub Container Registry.
- Produktion: eine VM in einem Schweizer Rechenzentrum mit Compose. Tägliches `pg_dump` und MinIO-Mirror auf separaten Speicher.
- Skalierung später: mehr Worker-Container für parallele Prüfläufe; der Wechsel auf Kubernetes ist ohne Code-Änderung möglich.

## Tests und KI-Evaluation

Die Regel-Engine wird klassisch getestet, die KI-Teile über ein Evaluations-Set mit echten Dossiers. Ohne dieses Set ist kein Modellwechsel und keine Prompt-Änderung beurteilbar.

| Ebene | Was | Wann |
| --- | --- | --- |
| Unit-Tests | Regelauflösung (Kanton plus Gemeinde-Overrides), Bedingungen, Befundlogik | Jeder Commit |
| Regel-Validierung | Alle YAML-Dateien gegen `schema.json`, eindeutige IDs, Quelle und Stand gesetzt | Jeder Commit |
| Szenario-Tests | Pro Vorhabenstyp und Gemeinde: erwartete Beilagenliste | Jeder Commit |
| KI-Evaluation | Plantyp-Erkennung und Merkmalsextraktion gegen Referenzantworten, Treffergenauigkeit pro Prüfung und Modell | Bei Modell- oder Prompt-Änderung, wöchentlich |
| End-to-End | Komplettes Testdossier durch die Pipeline im Compose-Stack | Vor jedem Release |

**Evaluations-Set aufbauen:** 15 bis 20 reale Dossiers aus den Pilotbüros, mit deren Einverständnis, verteilt auf beide Kantone und alle MVP-Vorhabenstypen. Pro Seite werden Plantyp und Merkmale einmal von Hand annotiert. Overrides der Planer im Betrieb ergänzen das Set laufend.

**Vorgeschlagene Zielwerte vor dem Pilot:** Plantyp-Erkennung mindestens 95 % richtig, Merkmalsextraktion mindestens 90 %, und kein «erfüllt», wo die Unterlage tatsächlich fehlt. Ein falsches «fehlt» kostet den Planer eine Minute, ein falsches «erfüllt» kostet ihn eine Rückweisung.

## Datenschutz und Sicherheit

Baugesuche enthalten Personendaten der Bauherrschaft, Grundstücksdaten und Pläne. Die kritischste Stelle ist der KI-Aufruf, weil dort Daten den eigenen Stack verlassen.

- **Hosting:** Alle Container auf einer VM in der Schweiz. Datenbank- und Speicher-Volumes verschlüsselt, TLS über Caddy.
- **KI-Anbieter:** Ein Anbieter mit vertraglich zugesicherter Datenverarbeitung in der Schweiz oder EU und ohne Training auf Kundendaten. Vor dem Aufruf werden nur Planseiten und Formularausschnitte gesendet, keine ganzen Dossiers.
- **Lokale Option:** Klassifikation über Text-Heuristik und ein lokal betriebenes Modell als optionaler Container. Die Genauigkeit muss über das Evaluations-Set belegt werden, bevor das eine Alternative ist.
- **Aufbewahrung:** Dossiers werden nach `RETENTION_DAYS` (Vorschlag 30 Tage) automatisch gelöscht, ein nächtlicher Job im Worker erledigt das. Für das Evaluations-Set nur Dossiers mit ausdrücklichem Einverständnis.
- **Mandantentrennung:** Jedes Büro sieht nur seine Dossiers; Objektpfade in MinIO pro Büro getrennt, Zugriff nur über signierte, kurzlebige URLs.
- **Logging:** Keine Dokumentinhalte in Logs, nur IDs, Laufzeiten und Fehlercodes.
- **Verträge:** Auftragsverarbeitungsvertrag mit jedem Büro nach revDSG; KI-Anbieter und Hoster als Unterauftragsverarbeiter aufführen.

## Risiken und offene Entscheidungen

Das grösste Risiko ist nicht die Technik, sondern die Pflege des Regelkatalogs über viele Gemeinden.

| Risiko | Gegenmassnahme |
| --- | --- |
| Regelkatalog veraltet, weil Erlasse und Merkblätter ändern | Feld `stand` pro Regel, Quellen-URLs halbjährlich automatisch auf Änderungen prüfen |
| Gemeindeanforderungen schlecht dokumentiert | Kantonale Basis zuerst, Gemeinden nur als Overrides; Pilotbüros melden Lücken |
| KI-Genauigkeit reicht für einzelne Merkmale nicht | Solche Prüfungen als `manuell` führen, bis das Evaluations-Set sie belegt |
| Grosse Pläne verlieren Details beim Rendern | Kachelung mit Überlappung, Auflösung pro Plantyp konfigurierbar |
| Lizenz bei Nutzung des Inosca-Codes | Inosca ist GPL-lizenziert: Formulardefinitionen als Datenquelle lesen, keinen Code ins eigene Produkt übernehmen |
| Zu wenig echte Dossiers für die Evaluation | Pilotbüros früh gewinnen, Einverständnis zur Nutzung schriftlich |

**Offene Entscheidungen**

- [ ] KI-Anbieter und Modell festlegen (Datenstandort, Kosten pro Dossier)
- [ ] Hosting-Anbieter in der Schweiz wählen
- [ ] Pilotgemeinden pro Kanton bestätigen
- [ ] Zwei bis drei Pilotbüros gewinnen
- [ ] Inosca-Repository auf Schwyzer Formulardefinitionen prüfen
- [ ] Preismodell (pro Dossier oder Abo pro Büro)
