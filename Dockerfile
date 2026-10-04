# syntax=docker/dockerfile:1
# Ein Image für web und worker; der Startbefehl wird von Compose gesetzt.

FROM python:3.12-slim AS builder

# Grosse Wheels (z. B. litellm) brauchen bei langsamer Leitung länger: höhere Timeouts, Retries und ein
# BuildKit-Cache, damit ein Wiederholungslauf bereits geladene Wheels nicht erneut holt.
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY pyproject.toml ./
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/pip pip install .

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-deu \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libfontconfig1 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 planklar \
    && useradd --system --uid 10001 --gid planklar --home-dir /srv --shell /usr/sbin/nologin planklar

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv
COPY --chown=planklar:planklar app ./app
COPY --chown=planklar:planklar alembic.ini ./alembic.ini
# Regelkatalog im Image, damit Image-Tag und Regelstand zusammenpassen; per Volume überschreibbar.
COPY --chown=planklar:planklar rules ./rules

USER planklar
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

# Migrationen vor dem Start, da das Lifespan den Regelkatalog in die DB schreibt (Tabellen müssen existieren).
# Der Worker setzt seinen eigenen Startbefehl und migriert nicht.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
