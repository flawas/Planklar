from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.auth.oidc import ensure_oidc_disabled
from app.auth.router import admin_router, auth_router
from app.config import get_settings
from app.db.session import get_sessionmaker
from app.dossiers.router import dossier_router
from app.logging_setup import configure_logging, install_request_logging
from app.rules.store import lade_katalog
from app.web.router import BASE_DIR, web_router

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Lädt den Regelkatalog; ein ungültiger Katalog (RegelLadeFehler) bricht den Start ab."""
    with get_sessionmaker()() as session:
        lade_katalog(session, get_settings().git_commit)
    yield


app = FastAPI(title="Liquet", lifespan=lifespan)
install_request_logging(app)
ensure_oidc_disabled(get_settings())
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(dossier_router)
app.include_router(web_router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
