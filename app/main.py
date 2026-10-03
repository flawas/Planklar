from fastapi import FastAPI

from app.auth.oidc import ensure_oidc_disabled
from app.auth.router import admin_router, auth_router
from app.config import get_settings
from app.logging_setup import configure_logging, install_request_logging

configure_logging()

app = FastAPI(title="Planklar")
install_request_logging(app)
ensure_oidc_disabled(get_settings())
app.include_router(auth_router)
app.include_router(admin_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
