# Nutzungsbasierte Abrechnung (LLM)

Jeder LLM-Aufruf einer Prüfung wird dem Büro zugeordnet und in `llm_nutzung` festgehalten
(Migration 0014, mit RLS wie die übrigen Mandantentabellen).

- **Erfasst:** Büro, Prüflauf-ID, Zweck (`klassifikation`, `merkmal`, `sonstiges`), tatsächliches Modell,
  Input-/Output-Tokens, Kosten in USD laut LiteLLM-Preisliste zum Aufrufzeitpunkt (`NULL`, wenn das Modell
  keinen bekannten Preis hat). Nie Frage, Bild oder Antwort.
- **Erfassung:** `app.abrechnung.nutzung.nutzung_erfassen(buero_id, pruefung_id)` umschliesst die Seitenverarbeitung
  in `run_pruefung`. `ask()` meldet den Verbrauch an die Senke (auch bei ungültiger Antwort, die Tokens sind
  verbraucht). Jede Buchung ist eine eigene, sofort committete Transaktion; ein Fehler dort bricht die Prüfung nicht ab.
- **Nicht erfasst:** der Verbindungstest in den KI-Einstellungen (Plattform, kein Büro) und `eval.run`.
  Fehlgeschlagene Anbieteraufrufe liefern keine Token-Angaben und erscheinen nicht.
- **Auswertung:** `GET /plattform/abrechnung?monat=JJJJ-MM` (Plattform-Admin): je Büro Aufrufe, Token und Kosten,
  aufgeschlüsselt nach Modell. `ohne_preis` zählt Aufrufe ohne bekannten Preis; die Kostensumme ist dann eine Untergrenze.
- **Offen (bewusst nicht Teil der Grundlage):** Preismodell/Aufschlag pro Büro, Rechnungserzeugung,
  Ansicht für `buero_admin` (`BueroScope.llm_nutzung_summen` ist vorbereitet).
