from fastapi import FastAPI

from app.logging_setup import configure_logging, install_request_logging

configure_logging()

app = FastAPI(title="Planklar")
install_request_logging(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
