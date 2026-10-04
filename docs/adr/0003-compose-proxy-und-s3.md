# 0003 – Compose-Stack: Caddy-Proxy und SeaweedFS statt MinIO

## Kontext
Der Plan ("Docker-Setup") nennt `minio/minio` als Objektspeicher. Das Image ist auf Docker Hub nicht mehr verfügbar (`pull access denied`), `quay.io/minio/minio` verlangt Authentifizierung. `bitnamilegacy/minio` ist eingefroren, `cgr.dev/chainguard/minio` hat nur `latest`. Ausserdem fehlte im Stack der Proxy.

## Entscheidung
- Objektspeicher ist SeaweedFS (S3-API, `chrislusf/seaweedfs`) mit festem Tag. Der Dienst heisst `s3`, Endpunkt `S3_ENDPOINT=http://s3:8333`.
- Caddy (`caddy:2.11.6-alpine`) läuft als Dienst `proxy` vor `web`. Die Adresse kommt aus `SITE_ADDRESS`: lokal `:80` ohne TLS, in Produktion der Hostname mit automatischem TLS.
- Alle Image-Tags sind fest. Beim Aktualisieren wird der Tag bewusst angehoben.

## Konsequenzen
- Der Plan-Abschnitt "Docker-Setup" und ADR 0001 ("MinIO") gelten für den Speicher nicht mehr wörtlich; S3-kompatible Clients (`boto3`) bleiben unverändert.
- Der S3-Zugriff im Code darf keine MinIO-spezifischen Funktionen nutzen.
- Der Speicher läuft ohne Zugangsdaten und ist nur im Compose-Netz bzw. lokal auf Port 8333 erreichbar; für Produktion sind S3-Credentials noch zu konfigurieren.
