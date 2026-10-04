# Inosca (ebau): Schwyzer Formulardefinitionen

Recherche zu Issue #49. Stand der Prüfung: 2026-10-04, Repository `github.com/inosca/ebau`, Commit `0448ac6` (16.09.2026). Kein Code wurde übernommen.

## Ergebnis in Kürze

- Ja, die Schwyzer Formulardefinitionen sind maschinenlesbar im Repository enthalten.
- Sie liegen als JSON unter `django/kt_schwyz/`. Es sind Caluma-Formularexporte, keine Regeln.
- Lizenz des Repositories: **EUPL-1.2-or-later** (`LICENSE`, `README.md` Abschnitt License). Der Plan und `rules.md` nennen «GPL»; das stimmt für das Repository `inosca/ebau` nicht. Die Organisation führt zudem GPL-3.0 (`ebau-gwr`), AGPL-3.0 (`ember-ebau-gwr`), MIT und Apache-2.0 (Keycloak-Hilfen). Die Rechtsgrundlage für die Nutzung der Definitionen als Datenquelle ist in jedem Fall zu klären (siehe Risiken).
- Empfehlung: Definitionen nur als **Referenz** lesen, die Regeln selbst aus den amtlichen Quellen (§ 77 PBG SZ, SRSZ 400.111, Wegleitungen) formulieren und die Inosca-Dateien höchstens als Querverweis in der Quellenangabe nennen. Keine automatische Übernahme.

## Fundorte

| Pfad (unter `django/kt_schwyz/`) | Inhalt | Nutzen für Liquet |
| --- | --- | --- |
| `form.json` (ca. 600 KB) | Schlüssel `forms` (80 Formularversionen), `modules` (82), `questions` (699) | Hauptquelle: Fragen, Pflichtangaben, Sichtbarkeitsbedingungen |
| `config/caluma_form.json` | Django-Fixture (`caluma_form.form/question/option/...`), 13 Formulare | Nur Verwaltungsformulare der Behörde (Bauverwaltung, Voranfrage); für Gesuchsteller nicht relevant |
| `config/alexandria_core.json` | 15 Dokumentkategorien (z. B. «Projektpläne und Projektbeschrieb», «Grundstücksangaben») | Hinweis auf Beilagenkategorien |
| `config/document.json`, `data/*.json` | Konfiguration und Betriebsdaten | nicht relevant, `data/` enthält Betriebsdaten und ist zu meiden |

`data/*.json` (u. a. `user.json`, `instance.json`) kann Betriebs- bzw. Personendaten enthalten und darf **nicht** in dieses Repository gelangen.

## Format

`form.json` ist ein Caluma-Export (Schlüssel `forms`, `modules`, `questions`).

- `forms`: Formular-ID auf geordnete Liste von Modulen. Relevante Gesuchsformulare: `baugesuch-reklamegesuch` (bis `-v13`), `projektanderung`, `vorentscheid-gemass-ss84-pbg`, `vorabklarung`, `baumeldung-fur-geringfugiges-vorhaben`, `technische-bewilligung`, `plangenehmigungsgesuch`, `abbruchpraemie` u. a. Versionen (`-vN`) sind nummerierte Kopien; die höchste Version gilt für neue Gesuche.
- `modules`: Name auf `{title, parent, questions[]}`. Das Modul `gesuchsunterlagen` bündelt die Beilagen.
- `questions`: Frage-ID auf `{label, hint, type, required, config, active-expression, restrict}`. Typen (Anzahl): radio 190, text 187, checkbox 162, number-separator 47, number 44, table 36, textarea 11, date 11, **document 9**, gwr 2.
- `active-expression` ist ein JEXL-Ausdruck für die Sichtbarkeit, z. B. `'landwirtschaft-veranderung-tierbestand'|value == 'Ja'`. Er ist nicht JSON Logic und müsste in `when` übersetzt werden.
- Mehrsprachige Labels sind bei Schwyz einsprachig Deutsch.

## Inhalt mit Bezug zu Beilagen

- Neun Fragen vom Typ `document`. Vier gehören zum Modul `gesuchsunterlagen`: `dokument-grundstucksangaben` (Pflicht), `dokument-projektplane-projektbeschrieb` (Pflicht), `dokument-gutachten-nachweise-begrundungen` (optional), `dokument-weitere-gesuchsunterlagen` (optional). Zwei weitere Pflichtdokumente hängen an einer Bedingung (Baustellenentwässerung: `dokument-baustelleninstallationsplan`, `dokument-plan-einleitstelle-leitungskatasterplan-versickerungsfläche`).
- 62 `info-*`-Fragen (Checkbox «Vorhanden», nicht Pflicht) nennen bedingte Beilagen, z. B. Formular Tierbestand bei Tierbestandsänderung, Sicherheitsdatenblätter bei Gaslager, forstliche Begründung bei Wald. Rund 37 davon enthalten einen Beilagenhinweis. Verlinkt sind PDF-Formulare (`/assets/documents/...`) und amtliche Seiten (`sz.ch`, `map.geo.sz.ch`).
- Kantonale Gesamtdefinition: kein Gemeindebezug. Die Schwyzer Gemeinden sind nicht als eigene Formularvarianten modelliert; gemeindespezifische Beilagen (Baureglemente) sind darin **nicht** enthalten.
- Keine Rechtsquellen: Weder Erlass noch Paragraph sind je Frage hinterlegt (nur Freitext in `label`/`hint`).

## Eignung für Liquet

Passend:
- Vollständige, aktuelle Liste der Gesuchstypen und Fachthemen als Gliederungshilfe für Vorhabentypen (`rules/SZ`).
- Welche Beilagen bei welcher Antwort verlangt werden (`active-expression` + `info-*`).
- Beilagenkategorien aus `alexandria_core.json`.

Nicht passend oder fehlend:
- Prüfmethoden (`ki_klassifikation`, `plan_merkmal` usw.), `schwere` und `quelle` fehlen. Jede Regel braucht laut Domain-Regeln eine belegbare Quelle mit Erlass, Paragraph, URL und `stand`; diese liefert Inosca nicht.
- Teile gehen über formelle Vollständigkeit hinaus (z. B. Fachthemen mit materieller Relevanz); diese bleiben ausgeschlossen.
- Der Export bildet das Online-Formular ab, nicht das Papierverfahren; Abweichungen sind möglich.

## Empfehlung

1. **Nicht automatisch importieren.** Kein Konverter, der `form.json` in `rules/SZ` schreibt: Die Quellenpflicht wäre verletzt, und JEXL-Ausdrücke lassen sich nicht ohne Prüfung in JSON Logic übertragen.
2. **Als Checkliste verwenden.** Beim Schreiben der SZ-Regeln (Folge-Issues) die `info-*`-Fragen und die `document`-Fragen durchgehen und prüfen, ob eine Beilage in der amtlichen Quelle (§ 77 PBG, SRSZ 400.111, Wegleitung des Kantons) belegt ist. Nur dann Regel schreiben; sonst Kommentar im Issue.
3. **Quelle ehrlich angeben.** Die Regel zitiert den Erlass, nicht Inosca. Falls eine Definition als Anhaltspunkt diente, im YAML-Kommentar vermerken: `# Anhaltspunkt: inosca/ebau, django/kt_schwyz/form.json, Frage <id>, Commit <hash>`.
4. **Keine Dateien einchecken.** `form.json` nicht ins Repository kopieren (Lizenz, Umfang, Änderungsstand). Bei Bedarf Abruf per Skript ausserhalb von CI; das Skript darf nichts aus `data/` lesen.
5. **Lizenz klären.** Die EUPL-1.2 ist Copyleft. Ob Formularinhalte (Fragetexte, Struktur) darunter fallen und ob eine Ableitung Auflagen auslöst, sollte vor einer allfälligen direkten Übernahme juristisch geklärt werden. Zusätzlich beim Kanton Schwyz nachfragen, ob die Inhalte offen nutzbar sind. Bis dahin: Referenz ja, Übernahme nein.
6. **Aktualität.** Die Formulare ändern sich laufend (Version `-v13`). Bei Regelpflege den Commit festhalten und `stand` entsprechend setzen.

## Offene Punkte

- Juristische Einordnung EUPL-1.2 für Formularinhalte (Punkt 5). Bleibt für die Rechtsprüfung der Projektleitung.
- Plan (`Implementationsplan Baugesuch-Check.md`, Zeilen 103/209) und `.claude/agents/rules.md` sprechen von «GPL». Korrektur auf EUPL-1.2 für `inosca/ebau` empfohlen; nicht Teil dieses Issues.
