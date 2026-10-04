import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.users import (
    COOKIE_NAME,
    UserManager,
    cookie_backend,
    get_user_manager,
)
from app.config import get_settings
from app.db.models import User
from app.db.session import get_session
from app.dossiers.scope import BueroScope, NotFoundError
from app.dossiers.service import UploadError, basename, get_storage, upload_dokument
from app.pipeline import llm_config
from app.storage import Storage
from app.web import csrf, ki_einstellungen, unterlagen, vorhaben

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

web_router = APIRouter(tags=["web"], include_in_schema=False)

MSG_LOGIN = "E-Mail oder Passwort ist falsch."
MSG_CSRF = "Die Sitzung des Formulars ist abgelaufen. Bitte versuchen Sie es erneut."
MSG_UPLOAD = {
    "FILE_TOO_LARGE": "Die Datei ist zu gross.",
    "NOT_A_PDF": "Die Datei ist kein PDF.",
    "PDF_INVALID": "Das PDF ist beschädigt oder leer.",
    "PDF_ENCRYPTED": "Das PDF ist passwortgeschützt.",
    "DUPLICATE": "Doppelt: Dieses Dokument ist im Dossier bereits vorhanden.",
}
MSG_KEINE_DATEI = "Bitte wählen Sie mindestens eine Datei aus."
MSG_SCHRITT = "Ungültiger Schritt im Assistenten."
MSG_NOT_LOGGED_IN = "Bitte melden Sie sich an."
MSG_GESPEICHERT = "Einstellungen gespeichert."


@dataclass
class UploadErgebnis:
    """View-Model einer Ergebniszeile pro hochgeladener Datei."""

    dateiname: str
    ok: bool
    meldung: str


def _render(
    request: Request,
    name: str,
    *,
    user: User | None = None,
    status_code: int = 200,
    token: str | None = None,
    **context: object,
) -> HTMLResponse:
    token = token or request.cookies.get(csrf.CSRF_COOKIE)
    fresh = not csrf.is_valid(token)
    if fresh:
        token = csrf.new_token()
    response = templates.TemplateResponse(
        request,
        name,
        {"user": user, "csrf_token": token, **context},
        status_code=status_code,
    )
    if fresh:
        s = get_settings()
        response.set_cookie(
            csrf.CSRF_COOKIE,
            token or "",
            httponly=True,
            secure=s.auth_cookie_secure,
            samesite=s.auth_cookie_samesite,
        )
    return response


async def _optional_user(
    request: Request,
    manager: UserManager = Depends(get_user_manager),
) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    user = await cookie_backend.get_strategy().read_token(token, manager)
    return user if user and user.is_active else None


@web_router.get("/", response_model=None)
def home(request: Request, user: Annotated[User | None, Depends(_optional_user)]) -> Response:
    if user is None:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    return _render(request, "home.html", user=user)


@web_router.get("/login", response_model=None)
def login_form(request: Request, user: Annotated[User | None, Depends(_optional_user)]) -> Response:
    if user is not None:
        return RedirectResponse("/", status.HTTP_303_SEE_OTHER)
    return _render(request, "login.html", email="")


@web_router.post("/login", response_model=None)
async def login(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()] = "",
    manager: UserManager = Depends(get_user_manager),
) -> Response:
    if not csrf.matches(request.cookies.get(csrf.CSRF_COOKIE), csrf_token):
        return _render(request, "login.html", status_code=403, error=MSG_CSRF, email=email)
    user = await manager.authenticate(OAuth2PasswordRequestForm(username=email, password=password))
    if user is None or not user.is_active:
        return _render(request, "login.html", status_code=400, error=MSG_LOGIN, email=email)
    login_response = await cookie_backend.login(cookie_backend.get_strategy(), user)
    await manager.on_after_login(user, request, login_response)
    # Session-Cookie übernehmen, Antwort in Weiterleitung umwandeln
    login_response.status_code = status.HTTP_303_SEE_OTHER
    login_response.headers["location"] = "/"
    return login_response


@web_router.post("/logout", response_model=None)
def logout(request: Request, csrf_token: Annotated[str, Form()] = "") -> Response:
    if not csrf.matches(request.cookies.get(csrf.CSRF_COOKIE), csrf_token):
        return _render(request, "login.html", status_code=403, error=MSG_CSRF, email="")
    response = RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    s = get_settings()
    response.delete_cookie(
        COOKIE_NAME,
        secure=s.auth_cookie_secure,
        httponly=True,
        samesite=s.auth_cookie_samesite,
    )
    return response


@web_router.get("/dossiers/{dossier_id}/ansicht", response_model=None)
def dossier_seite(
    request: Request,
    dossier_id: uuid.UUID,
    user: Annotated[User | None, Depends(_optional_user)],
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    scope = BueroScope(session, user.buero_id)
    try:
        dossier = scope.get_dossier(dossier_id)
    except NotFoundError:
        return _render(request, "nicht_gefunden.html", user=user, status_code=404)
    dokumente = scope.list_dokumente(dossier.id)
    return _render(
        request,
        "dossier.html",
        user=user,
        dossier=dossier,
        dokumente=dokumente,
        unterlagen=unterlagen.unterlagen_zeilen(dossier, dokumente),
        ergebnisse=[],
    )


@web_router.post("/dossiers/{dossier_id}/upload", response_model=None)
async def dossier_upload(
    request: Request,
    dossier_id: uuid.UUID,
    user: Annotated[User | None, Depends(_optional_user)],
    files: Annotated[list[UploadFile] | None, File()] = None,
    csrf_token: Annotated[str, Form()] = "",
    session: Session = Depends(get_session),
    storage: Storage = Depends(get_storage),
) -> Response:
    if user is None:
        return _render(request, "_fehler.html", status_code=401, error=MSG_NOT_LOGGED_IN)
    if not csrf.matches(request.cookies.get(csrf.CSRF_COOKIE), csrf_token):
        return _render(request, "_fehler.html", user=user, status_code=403, error=MSG_CSRF)
    scope = BueroScope(session, user.buero_id)
    try:
        dossier = scope.get_dossier(dossier_id)
    except NotFoundError:
        return _render(request, "nicht_gefunden.html", user=user, status_code=404)
    files = [f for f in files or [] if f.filename]
    if not files:
        return _render(request, "_fehler.html", user=user, status_code=400, error=MSG_KEINE_DATEI)
    limit = get_settings().max_upload_bytes
    ergebnisse: list[UploadErgebnis] = []
    for file in files:
        name = basename(file.filename or "")
        data = await file.read(limit + 1)  # nie mehr als Limit + 1 Byte in den Speicher
        try:
            dok = upload_dokument(session, storage, dossier, name, data, limit)
            ergebnisse.append(UploadErgebnis(name, True, f"Hochgeladen ({dok.seitenzahl} Seiten)."))
        except UploadError as exc:
            ergebnisse.append(UploadErgebnis(name, False, MSG_UPLOAD[exc.code]))
    dokumente = scope.list_dokumente(dossier.id)
    return _render(
        request,
        "_dokumente.html",
        user=user,
        dossier=dossier,
        dokumente=dokumente,
        unterlagen=unterlagen.unterlagen_zeilen(dossier, dokumente),
        ergebnisse=ergebnisse,
    )


def _schritt_antwort(
    request: Request, user: User, view: vorhaben.SchrittView, status_code: int = 200
) -> HTMLResponse:
    """Partial bei HTMX, sonst vollständige Seite (Fallback ohne JavaScript)."""
    name = "_vorhaben_schritt.html" if request.headers.get("HX-Request") else "vorhaben.html"
    return _render(request, name, user=user, status_code=status_code, v=view)


@web_router.get("/vorhaben/neu", response_model=None)
def vorhaben_neu(
    request: Request, user: Annotated[User | None, Depends(_optional_user)]
) -> Response:
    if user is None:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    return _schritt_antwort(request, user, vorhaben.SchrittView(schritt=1, werte={}))


@web_router.post("/vorhaben/schritt", response_model=None)
async def vorhaben_schritt(
    request: Request,
    user: Annotated[User | None, Depends(_optional_user)],
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return _render(request, "_fehler.html", status_code=401, error=MSG_NOT_LOGGED_IN)
    form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    if not csrf.matches(request.cookies.get(csrf.CSRF_COOKIE), form.get("csrf_token")):
        return _render(request, "_fehler.html", user=user, status_code=403, error=MSG_CSRF)
    try:
        schritt = int(form.get("schritt", "1"))
    except ValueError:
        schritt = 0
    if not 1 <= schritt <= vorhaben.LETZTER_SCHRITT:
        return _render(request, "_fehler.html", user=user, status_code=400, error=MSG_SCHRITT)
    werte = vorhaben.bereinigen(form)
    aktion = form.get("aktion", "weiter")
    if aktion == "zurueck":
        return _schritt_antwort(request, user, vorhaben.SchrittView(max(1, schritt - 1), werte))
    fehler = vorhaben.pruefe_schritt(schritt, werte)
    if fehler:
        view = vorhaben.SchrittView(schritt, werte, fehler)
        return _schritt_antwort(request, user, view, status_code=422)
    if schritt < vorhaben.LETZTER_SCHRITT:
        return _schritt_antwort(request, user, vorhaben.SchrittView(schritt + 1, werte))
    neu = vorhaben.zu_dossier(werte)
    if neu is None:
        view = vorhaben.SchrittView(schritt, werte, meldung=vorhaben.MSG_ALLGEMEIN)
        return _schritt_antwort(request, user, view, status_code=422)
    dossier = BueroScope(session, user.buero_id).add_dossier(**neu.model_dump())
    session.commit()
    ziel = f"/dossiers/{dossier.id}/ansicht"
    if request.headers.get("HX-Request"):
        return Response(status_code=204, headers={"HX-Redirect": ziel})
    return RedirectResponse(ziel, status.HTTP_303_SEE_OTHER)


def _ki_seite(
    request: Request,
    user: User,
    session: Session,
    *,
    werte: dict[str, str] | None = None,
    fehler: dict[str, str] | None = None,
    meldung: str = "",
    ok: bool = True,
    status_code: int = 200,
) -> HTMLResponse:
    row = llm_config.get_row(session)
    gespeichert = {"modell": row.modell, "api_base": row.api_base} if row else {}
    return _render(
        request,
        "ki_einstellungen.html",
        user=user,
        status_code=status_code,
        werte=werte or {"modell": "", "api_base": "", **gespeichert},
        fehler=fehler or {},
        key_gesetzt=bool(row and row.api_key_verschluesselt),
        vorschlaege=ki_einstellungen.MODELL_VORSCHLAEGE,
        meldung=meldung,
        ok=ok,
    )


@web_router.get("/einstellungen/ki", response_model=None)
def ki_einstellungen_form(
    request: Request,
    user: Annotated[User | None, Depends(_optional_user)],
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    if not user.is_superuser:
        return _render(request, "nicht_gefunden.html", user=user, status_code=404)
    return _ki_seite(request, user, session)


@web_router.post("/einstellungen/ki", response_model=None)
def ki_einstellungen_speichern(
    request: Request,
    user: Annotated[User | None, Depends(_optional_user)],
    modell: Annotated[str, Form()] = "",
    api_base: Annotated[str, Form()] = "",
    api_key: Annotated[str, Form()] = "",
    clear_key: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return _render(request, "_fehler.html", status_code=401, error=MSG_NOT_LOGGED_IN)
    if not user.is_superuser:
        return _render(request, "nicht_gefunden.html", user=user, status_code=404)
    if not csrf.matches(request.cookies.get(csrf.CSRF_COOKIE), csrf_token):
        return _render(request, "_fehler.html", user=user, status_code=403, error=MSG_CSRF)
    werte = {"modell": modell.strip(), "api_base": api_base.strip()}
    fehler = ki_einstellungen.validiere(werte["modell"], werte["api_base"])
    if fehler:
        return _ki_seite(request, user, session, werte=werte, fehler=fehler, status_code=422)
    llm_config.save_config(
        session,
        model=werte["modell"],
        api_base=werte["api_base"],
        api_key=api_key.strip() or None,
        clear_key=bool(clear_key),
    )
    return _ki_seite(request, user, session, meldung=MSG_GESPEICHERT)


@web_router.post("/einstellungen/ki/test", response_model=None)
def ki_verbindung_testen(
    request: Request,
    user: Annotated[User | None, Depends(_optional_user)],
    csrf_token: Annotated[str, Form()] = "",
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return _render(request, "_fehler.html", status_code=401, error=MSG_NOT_LOGGED_IN)
    if not user.is_superuser:
        return _render(request, "nicht_gefunden.html", user=user, status_code=404)
    if not csrf.matches(request.cookies.get(csrf.CSRF_COOKIE), csrf_token):
        return _render(request, "_fehler.html", user=user, status_code=403, error=MSG_CSRF)
    if not llm_config.load_config(session).model:
        return _ki_seite(
            request, user, session, meldung=ki_einstellungen.MSG_TEST_KEIN_MODELL, ok=False
        )
    ok, meldung = ki_einstellungen.verbindung_testen()
    return _ki_seite(request, user, session, meldung=meldung, ok=ok)
