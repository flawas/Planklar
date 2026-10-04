# 0005 – Mandanten und Rollen

Status: **Angenommen** (Issue #132, Epic #130).

## Kontext
Die Datentrennung zwischen Büros steht (`BueroScope`, `buero_id` auf Dossier, S3-Pfad `buero/<id>/…`, Fremdzugriff-Test). Für den Betrieb mit mehreren Büros als Kunden fehlen Rollen, Benutzerverwaltung, Büro-Onboarding und eine zweite Schutzschicht in der Datenbank.

Heute bedeutet `is_superuser` zweierlei: Büro-Admin (`POST /admin/users`) und Plattform-Admin (globale KI-Einstellungen, ADR 0004). Das lässt sich nicht trennen, solange es nur ein Flag gibt.

## Entscheidung
1. **Ein Benutzer gehört zu genau einem Büro** (`user.buero_id` NOT NULL, `email` global eindeutig). Berater für mehrere Büros erhalten pro Büro ein eigenes Konto.
2. **Rollen**: Enum `Rolle` mit `mitarbeiter` und `buero_admin`, dazu das separate Flag `is_plattform_admin`. Es ersetzt die Plattform-Bedeutung von `is_superuser`.
   - `mitarbeiter`: Dossiers und Prüfläufe im eigenen Büro.
   - `buero_admin`: zusätzlich Benutzer und Einstellungen des eigenen Büros.
   - Plattform-Admin: Büros anlegen und sperren, KI-Einstellungen. Sieht nur Metadaten (Name, Anzahl Benutzer/Dossiers, Status), nie Dossierinhalte (revDSG).
   - Migration: bestehende `is_superuser=true` werden `buero_admin`; `is_plattform_admin` erhalten nur explizit benannte Konten, damit niemand ausgesperrt wird. `is_superuser` bleibt als fastapi-users-Feld bestehen und wird auf `is_plattform_admin` abgebildet (Mapping in der Migration dokumentieren).
3. **Einladung statt Selbstregistrierung**: Der Büro-Admin lädt per E-Mail ein. Token einmalig, 7 Tage gültig, nur gehasht gespeichert. Passwort-Reset nutzt denselben Mechanismus und verrät nicht, ob eine E-Mail existiert.
4. **Defense in depth über PostgreSQL Row-Level Security** auf allen mandantengebundenen Tabellen, zusätzlich zu `BueroScope`. Policy `buero_id = current_setting('app.buero_id')::uuid`; `BueroScope` setzt `SET LOCAL app.buero_id` pro Transaktion. Die App nutzt eine DB-Rolle ohne `BYPASSRLS`. Voraussetzung ist `buero_id` auf Dokument, Seite, Prüfung und Befund. Worker und Retention-Job setzen den Kontext pro Büro.
5. **E-Mail-Versand über SMTP**, ausschliesslich per Umgebungsvariablen (`app/config.py`). Der Anbieter hat Schweizer Hosting; AVV und Unterauftragsverarbeiter laufen über #59 und #62.

## Verworfene Alternativen
- **Mehrfach-Mitgliedschaft** (ein Benutzer in mehreren Büros): braucht Büro-Wechsel in Sitzung, Rollen pro Mitgliedschaft und einen Mandantenkontext in jedem Token. Der Nutzen ist klein, das Risiko von Verwechslungen gross.
- **Schema pro Mandant**: Migrationen müssen pro Büro laufen, Connection-Handling und Tests werden aufwendig. RLS erreicht die Isolation mit einem Schema.
- **Datenbank pro Mandant**: stärkste Isolation, aber Betriebsaufwand (Backups, Migrationen, Pools) steht in keinem Verhältnis zur Büroanzahl in Luzern und Schwyz.

## Verhältnis zu ADR 0004
Die KI-Einstellungen (`ki_einstellung`, globaler Singleton) hängen heute an `is_superuser`. Sie werden zur Plattform-Rolle: Zugriff nur mit `is_plattform_admin`, ein Büro-Admin erhält 403. Anbieter- und Modellwahl bleiben unverändert; ADR 0004 regelt die Auswahl, dieser ADR die Berechtigung.

## Konsequenzen
- Die Umsetzung erfolgt in den Teil-Issues des Epics #130 (Migration, Dependencies `require_buero_admin`/`require_plattform_admin`, Benutzerverwaltung, Einladung, Onboarding, RLS, Audit-Log).
- RLS verlangt, dass jeder Pfad (Web, Worker, Retention) den Büro-Kontext setzt; sonst liefern Abfragen leere Resultate. Dafür gibt es eine zentrale Hilfsfunktion und je Pfad einen Test.
- Neue mandantengebundene Tabellen brauchen `buero_id`, RLS-Policy und einen Eintrag im Fremdzugriff-Test.
- Die Rollenmigration darf bestehende Konten nicht aussperren; sie wird mit Seed-Daten getestet.
