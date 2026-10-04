# Evaluations-Set

Pro Datei (`*.json`) ein annotiertes Set; Bilder liegen daneben (PNG/JPG, eine Seite je Bild).

```json
{
  "seiten": [
    {
      "id": "dossier1-s3",
      "bild": "dossier1-s3.png",
      "text": "Grundriss EG 1:100",
      "plantyp": "Grundriss",
      "merkmale": {
        "massstab": {"vorhanden": "ja", "wert": "1:100"},
        "nordpfeil": {"vorhanden": "nein"}
      }
    }
  ]
}
```

- `text` (optional): Textlayer der Seite für die Heuristik.
- `merkmale`: nur annotierte Merkmale werden bewertet. `vorhanden` ist `ja` oder `nein`;
  `wert` nur bei `ja` und Merkmalen mit Wert.

**Keine echten Baugesuchsdaten committen.** Nur synthetische Seiten oder solche mit
dokumentiertem Einverständnis ausserhalb des Repos (`--data <Verzeichnis>`).
