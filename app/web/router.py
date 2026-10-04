import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.auth import einladung as einladung_svc
from app.auth import plattform
from app.auth.users import (
    COOKIE_NAME,
    UserManager,
    buero_ist_aktiv,
    cookie_backend,
    get_user_manager,
)
from app.config import get_settings
from app.db.models import Dossier, Ergebnis, Pruefung, User
from app.db.session import get_session
from app.dossiers.pruefung import LEASE
from app.dossiers.router import start_pruefung_endpoint
from app.dossiers.scope import BueroScope, NotFoundError
from app.dossiers.service import UploadError, basename, get_storage, upload_dokument
from app.mail import Mailer, get_mailer, send_safely
from app.pipeline import llm_config
from app.reports import bericht as berichte
from app.reports.pdf import render_pdf
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
MSG_FORBIDDEN = "Dafür fehlt Ihnen die Berechtigung."
MSG_GESPEICHERT = "Einstellungen gespeichert."
MSG_BUERO_ANGELEGT = "Büro angelegt. Die Einladung an den ersten Administrator wurde versandt."
MSG_BUERO_EMAIL = "Diese E-Mail-Adresse hat bereits ein Konto."
MSG_BUERO_MAIL_UNGUELTIG = "Bitte geben Sie eine gültige E-Mail-Adresse an."
MSG_BUERO_NAME = "Bitte geben Sie einen Namen (max. 200 Zeichen) an."
MSG_BUERO_UNBEKANNT = "Büro nicht gefunden."


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
    return user if user and user.is_active and buero_ist_aktiv(user) else None


@web_router.get("/", response_model=None)
def home(request: Request, user: Annotated[User | None, Depends(_optional_user)]) -> Response:
    if user is None:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    return _render(request, "home.html", user=user)


@dataclass
class VorhabenZeile:
    """View-Model einer Zeile der Vorhaben-Übersicht."""

    dossier: Dossier
    typ: str
    dokumente: int
    pruefung: Pruefung | None


PRUEFSTATUS_TEXT = {
    "laeuft": "Läuft",
    "abgeschlossen": "Abgeschlossen",
    "fehlgeschlagen": "Fehlgeschlagen",
}


@web_router.get("/vorhaben", response_model=None)
def vorhaben_uebersicht(
    request: Request,
    user: Annotated[User | None, Depends(_optional_user)],
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    scope = BueroScope(session, user.buero_id)
    zeilen = [
        VorhabenZeile(
            dossier=d,
            typ=vorhaben.TYPEN.get(d.vorhabenstyp.value, d.vorhabenstyp.value),
            dokumente=len(scope.list_dokumente(d.id)),
            pruefung=next(iter(reversed(scope.list_pruefungen(d.id))), None),
        )
        for d in reversed(scope.list_dossiers())  # neueste zuerst
    ]
    return _render(
        request,
        "vorhaben_liste.html",
        user=user,
        zeilen=zeilen,
        pruefstatus=PRUEFSTATUS_TEXT,
    )


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


def _letzte_pruefung(scope: BueroScope, dossier_id: uuid.UUID) -> Pruefung | None:
    return next(iter(reversed(scope.list_pruefungen(dossier_id))), None)


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
        pruefung=_letzte_pruefung(scope, dossier.id),
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


@web_router.get("/dossiers/{dossier_id}/bearbeiten", response_model=None)
def vorhaben_bearbeiten(
    request: Request,
    dossier_id: uuid.UUID,
    user: Annotated[User | None, Depends(_optional_user)],
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    try:
        dossier = BueroScope(session, user.buero_id).get_dossier(dossier_id)
    except NotFoundError:
        return _render(request, "nicht_gefunden.html", user=user, status_code=404)
    view = vorhaben.SchrittView(
        schritt=1,
        werte=vorhaben.werte_aus_dossier(dossier),
        dossier_id=str(dossier.id),
    )
    return _schritt_antwort(request, user, view)


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
    dossier_id = ""
    if form.get("dossier_id"):
        try:
            dossier_id = str(uuid.UUID(form["dossier_id"]))
        except ValueError:
            return _render(request, "_fehler.html", user=user, status_code=400, error=MSG_SCHRITT)
    aktion = form.get("aktion", "weiter")
    if aktion == "zurueck":
        return _schritt_antwort(
            request, user, vorhaben.SchrittView(max(1, schritt - 1), werte, dossier_id=dossier_id)
        )
    fehler = vorhaben.pruefe_schritt(schritt, werte)
    if fehler:
        view = vorhaben.SchrittView(schritt, werte, fehler, dossier_id=dossier_id)
        return _schritt_antwort(request, user, view, status_code=422)
    if schritt < vorhaben.LETZTER_SCHRITT:
        return _schritt_antwort(
            request, user, vorhaben.SchrittView(schritt + 1, werte, dossier_id=dossier_id)
        )
    neu = vorhaben.zu_dossier(werte)
    if neu is None:
        view = vorhaben.SchrittView(
            schritt, werte, meldung=vorhaben.MSG_ALLGEMEIN, dossier_id=dossier_id
        )
        return _schritt_antwort(request, user, view, status_code=422)
    scope = BueroScope(session, user.buero_id)
    if dossier_id:
        try:
            dossier = scope.update_dossier(uuid.UUID(dossier_id), **neu.model_dump())
        except NotFoundError:
            return _render(request, "nicht_gefunden.html", user=user, status_code=404)
    else:
        dossier = scope.add_dossier(**neu.model_dump())
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
        key_unlesbar=bool(
            row
            and row.api_key_verschluesselt
            and not llm_config.key_lesbar(row.api_key_verschluesselt)
        ),
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
    if not user.is_plattform_admin:
        return _render(request, "_fehler.html", user=user, status_code=403, error=MSG_FORBIDDEN)
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
    if not user.is_plattform_admin:
        return _render(request, "_fehler.html", user=user, status_code=403, error=MSG_FORBIDDEN)
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
    if not user.is_plattform_admin:
        return _render(request, "_fehler.html", user=user, status_code=403, error=MSG_FORBIDDEN)
    if not csrf.matches(request.cookies.get(csrf.CSRF_COOKIE), csrf_token):
        return _render(request, "_fehler.html", user=user, status_code=403, error=MSG_CSRF)
    if not llm_config.load_config(session).model:
        return _ki_seite(
            request, user, session, meldung=ki_einstellungen.MSG_TEST_KEIN_MODELL, ok=False
        )
    ok, meldung = ki_einstellungen.verbindung_testen()
    return _ki_seite(request, user, session, meldung=meldung, ok=ok)


def _plattform_seite(
    request: Request,
    user: User,
    session: Session,
    *,
    meldung: str | None = None,
    ok: bool = True,
    werte: dict[str, str] | None = None,
    status_code: int = 200,
) -> Response:
    return _render(
        request,
        "plattform.html",
        user=user,
        status_code=status_code,
        bueros=plattform.liste_bueros(session),
        meldung=meldung,
        ok=ok,
        werte=werte or {"name": "", "admin_email": ""},
    )


def _plattform_pruefen(
    request: Request, user: User | None, csrf_token: str
) -> tuple[User | None, Response | None]:
    """Gemeinsame Zugriffsprüfung der Plattform-Aktionen (POST)."""
    if user is None:
        return None, _render(request, "_fehler.html", status_code=401, error=MSG_NOT_LOGGED_IN)
    if not user.is_plattform_admin:
        return None, _render(
            request, "_fehler.html", user=user, status_code=403, error=MSG_FORBIDDEN
        )
    if csrf_token is not None and not csrf.matches(
        request.cookies.get(csrf.CSRF_COOKIE), csrf_token
    ):
        return None, _render(request, "_fehler.html", user=user, status_code=403, error=MSG_CSRF)
    return user, None


@web_router.get("/plattform", response_model=None)
def plattform_uebersicht(
    request: Request,
    user: Annotated[User | None, Depends(_optional_user)],
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    if not user.is_plattform_admin:
        return _render(request, "_fehler.html", user=user, status_code=403, error=MSG_FORBIDDEN)
    return _plattform_seite(request, user, session)


@web_router.post("/plattform/neu", response_model=None)
def plattform_buero_anlegen(
    request: Request,
    background: BackgroundTasks,
    user: Annotated[User | None, Depends(_optional_user)],
    name: Annotated[str, Form()] = "",
    admin_email: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    session: Session = Depends(get_session),
    mailer: Mailer = Depends(get_mailer),
) -> Response:
    admin, fehler = _plattform_pruefen(request, user, csrf_token)
    if admin is None:
        return fehler  # type: ignore[return-value]
    werte = {"name": name.strip(), "admin_email": admin_email.strip()}
    if not werte["name"] or len(werte["name"]) > 200:
        return _plattform_seite(
            request, admin, session, meldung=MSG_BUERO_NAME, ok=False, werte=werte, status_code=422
        )
    try:
        TypeAdapter(EmailStr).validate_python(werte["admin_email"])
    except ValidationError:
        return _plattform_seite(
            request,
            admin,
            session,
            meldung=MSG_BUERO_MAIL_UNGUELTIG,
            ok=False,
            werte=werte,
            status_code=422,
        )
    try:
        _, mail = plattform.lege_buero_an(session, werte["name"], werte["admin_email"])
    except einladung_svc.EmailExistiertError:
        return _plattform_seite(
            request, admin, session, meldung=MSG_BUERO_EMAIL, ok=False, werte=werte, status_code=409
        )
    background.add_task(send_safely, mailer, mail)
    return _plattform_seite(request, admin, session, meldung=MSG_BUERO_ANGELEGT)


@web_router.post("/plattform/{buero_id}/name", response_model=None)
def plattform_buero_umbenennen(
    request: Request,
    buero_id: uuid.UUID,
    user: Annotated[User | None, Depends(_optional_user)],
    name: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    session: Session = Depends(get_session),
) -> Response:
    admin, fehler = _plattform_pruefen(request, user, csrf_token)
    if admin is None:
        return fehler  # type: ignore[return-value]
    if not name.strip() or len(name.strip()) > 200:
        return _plattform_seite(
            request, admin, session, meldung=MSG_BUERO_NAME, ok=False, status_code=422
        )
    try:
        plattform.benenne_um(session, buero_id, name)
    except plattform.BueroNotFoundError:
        return _plattform_seite(
            request, admin, session, meldung=MSG_BUERO_UNBEKANNT, ok=False, status_code=404
        )
    return _plattform_seite(request, admin, session, meldung=MSG_GESPEICHERT)


@web_router.post("/plattform/{buero_id}/status", response_model=None)
def plattform_buero_sperren(
    request: Request,
    buero_id: uuid.UUID,
    user: Annotated[User | None, Depends(_optional_user)],
    aktiv: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    session: Session = Depends(get_session),
) -> Response:
    admin, fehler = _plattform_pruefen(request, user, csrf_token)
    if admin is None:
        return fehler  # type: ignore[return-value]
    try:
        plattform.setze_aktiv(session, buero_id, aktiv == "1")
    except plattform.BueroNotFoundError:
        return _plattform_seite(
            request, admin, session, meldung=MSG_BUERO_UNBEKANNT, ok=False, status_code=404
        )
    return _plattform_seite(request, admin, session, meldung=MSG_GESPEICHERT)


MSG_BEGRUENDUNG = "Bitte geben Sie eine Begründung an."
MSG_START = {
    "KEINE_DOKUMENTE": "Bitte laden Sie zuerst Dokumente hoch.",
    "PRUEFUNG_LAEUFT": "Für dieses Dossier läuft bereits eine Prüfung.",
    "WORKER_NICHT_ERREICHBAR": "Die Prüfung konnte nicht gestartet werden. Bitte später versuchen.",
}
ERGEBNIS_OPTIONEN = [
    (Ergebnis.ERFUELLT, "Erfüllt"),
    (Ergebnis.FEHLT, "Fehlt"),
    (Ergebnis.UNSICHER, "Unsicher"),
    (Ergebnis.MANUELL, "Manuell prüfen"),
]


def _bericht_kontext(scope: BueroScope, dossier_id: uuid.UUID, pruefung_id: uuid.UUID) -> dict:  # type: ignore[type-arg]
    pruefung = scope.get_pruefung(pruefung_id)
    if pruefung.dossier_id != dossier_id:
        raise NotFoundError
    bericht = berichte.baue_bericht(scope, pruefung_id)
    return {
        "bericht": bericht,
        "pruefung": bericht.pruefung,
        "dossier": bericht.dossier,
        "modus": "web",
        "ergebnis_optionen": ERGEBNIS_OPTIONEN,
    }


@web_router.post("/dossiers/{dossier_id}/pruefen", response_model=None)
def pruefung_starten(
    request: Request,
    dossier_id: uuid.UUID,
    user: Annotated[User | None, Depends(_optional_user)],
    csrf_token: Annotated[str, Form()] = "",
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    htmx = bool(request.headers.get("HX-Request"))
    if not csrf.matches(request.cookies.get(csrf.CSRF_COOKIE), csrf_token):
        return _render(request, "_fehler.html", user=user, status_code=403, error=MSG_CSRF)
    scope = BueroScope(session, user.buero_id)
    try:
        pruefung = start_pruefung_endpoint(dossier_id, scope)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return _render(request, "nicht_gefunden.html", user=user, status_code=404)
        meldung = MSG_START.get(str(exc.detail), MSG_START["WORKER_NICHT_ERREICHBAR"])
        if htmx:
            return _pruefstatus_antwort(
                request, user, scope, dossier_id, fehler=meldung, status_code=exc.status_code
            )
        return _render(
            request, "_fehler.html", user=user, status_code=exc.status_code, error=meldung
        )
    if htmx:
        return _pruefstatus_antwort(request, user, scope, dossier_id)
    return RedirectResponse(
        f"/dossiers/{dossier_id}/pruefungen/{pruefung.id}/bericht", status.HTTP_303_SEE_OTHER
    )


def _pruefstatus_antwort(
    request: Request,
    user: User,
    scope: BueroScope,
    dossier_id: uuid.UUID,
    *,
    fehler: str | None = None,
    status_code: int = 200,
) -> Response:
    return _render(
        request, "_pruefstatus.html", user=user, status_code=status_code,
        dossier=scope.get_dossier(dossier_id), pruefung=_letzte_pruefung(scope, dossier_id),
        fehler=fehler,
    )  # fmt: skip


@web_router.get("/dossiers/{dossier_id}/pruefstatus", response_model=None)
def pruefstatus(
    request: Request,
    dossier_id: uuid.UUID,
    user: Annotated[User | None, Depends(_optional_user)],
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return _render(request, "_fehler.html", status_code=401, error=MSG_NOT_LOGGED_IN)
    scope = BueroScope(session, user.buero_id)
    try:
        scope.get_dossier(dossier_id)
        scope.hat_aktiven_lauf(dossier_id, LEASE)  # markiert verwaiste Läufe als fehlgeschlagen
        session.commit()
        return _pruefstatus_antwort(request, user, scope, dossier_id)
    except NotFoundError:
        return _render(request, "nicht_gefunden.html", user=user, status_code=404)


@web_router.get("/dossiers/{dossier_id}/pruefungen/{pruefung_id}/bericht", response_model=None)
def bericht_seite(
    request: Request,
    dossier_id: uuid.UUID,
    pruefung_id: uuid.UUID,
    user: Annotated[User | None, Depends(_optional_user)],
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    try:
        kontext = _bericht_kontext(BueroScope(session, user.buero_id), dossier_id, pruefung_id)
    except NotFoundError:
        return _render(request, "nicht_gefunden.html", user=user, status_code=404)
    name = "_bericht.html" if request.headers.get("HX-Request") else "bericht.html"
    return _render(request, name, user=user, **kontext)


@web_router.get("/dossiers/{dossier_id}/pruefungen/{pruefung_id}/bericht.pdf", response_model=None)
def bericht_pdf(
    request: Request,
    dossier_id: uuid.UUID,
    pruefung_id: uuid.UUID,
    user: Annotated[User | None, Depends(_optional_user)],
    session: Session = Depends(get_session),
) -> Response:
    if user is None:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    try:
        kontext = _bericht_kontext(BueroScope(session, user.buero_id), dossier_id, pruefung_id)
    except NotFoundError:
        return _render(request, "nicht_gefunden.html", user=user, status_code=404)
    if kontext["pruefung"].status.value != "abgeschlossen":
        return _render(request, "_fehler.html", user=user, status_code=409, error=MSG_PDF)
    pdf = render_pdf(templates.env, {"user": user, "csrf_token": "", **kontext})
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="pruefbericht-{pruefung_id}.pdf"'},
    )


def _befund_antwort(
    request: Request,
    user: User,
    scope: BueroScope,
    dossier_id: uuid.UUID,
    pruefung_id: uuid.UUID,
    befund_id: uuid.UUID,
    *,
    status_code: int = 200,
    fehler: str | None = None,
) -> Response:
    """Teil-Update eines Befunds bei HTMX, sonst Weiterleitung zum Bericht."""
    ziel = f"/dossiers/{dossier_id}/pruefungen/{pruefung_id}/bericht"
    if not request.headers.get("HX-Request"):
        if fehler:
            return _render(
                request, "_fehler.html", user=user, status_code=status_code, error=fehler
            )
        return RedirectResponse(f"{ziel}#befund-{befund_id}", status.HTTP_303_SEE_OTHER)
    kontext = _bericht_kontext(scope, dossier_id, pruefung_id)
    zeile = next(z for z in kontext["bericht"].zeilen if z.befund_id == befund_id)
    headers = {"HX-Retarget": f"#befund-{befund_id}", "HX-Reswap": "outerHTML"}
    response = _render(
        request, "_befund.html", user=user, status_code=status_code, z=zeile,
        fehler=fehler, fehler_befund=befund_id, **kontext,
    )  # fmt: skip
    response.headers.update(headers)
    return response


async def _befund_aktion(
    request: Request,
    dossier_id: uuid.UUID,
    pruefung_id: uuid.UUID,
    befund_id: uuid.UUID,
    user: User | None,
    session: Session,
    aktion: str,
) -> Response:
    if user is None:
        return _render(request, "_fehler.html", status_code=401, error=MSG_NOT_LOGGED_IN)
    form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    if not csrf.matches(request.cookies.get(csrf.CSRF_COOKIE), form.get("csrf_token")):
        return _render(request, "_fehler.html", user=user, status_code=403, error=MSG_CSRF)
    scope = BueroScope(session, user.buero_id)
    try:
        pruefung = scope.get_pruefung(pruefung_id)
        befund = scope.get_befund(befund_id)
        if pruefung.dossier_id != dossier_id or befund.pruefung_id != pruefung.id:
            raise NotFoundError
        if aktion == "override":
            try:
                ergebnis = Ergebnis(form.get("ergebnis", ""))
            except ValueError:
                return _befund_antwort(
                    request, user, scope, dossier_id, pruefung_id, befund_id,
                    status_code=422, fehler=MSG_ERGEBNIS,
                )  # fmt: skip
            begruendung = form.get("begruendung", "").strip()
            if not begruendung:
                return _befund_antwort(
                    request, user, scope, dossier_id, pruefung_id, befund_id,
                    status_code=422, fehler=MSG_BEGRUENDUNG,
                )  # fmt: skip
            scope.set_override(befund_id, ergebnis, begruendung[:2000])
        elif aktion == "bestaetigen":
            if befund.ergebnis != Ergebnis.MANUELL:
                return _befund_antwort(
                    request, user, scope, dossier_id, pruefung_id, befund_id,
                    status_code=409, fehler=MSG_NUR_MANUELL,
                )  # fmt: skip
            scope.set_override(befund_id, Ergebnis.ERFUELLT, berichte.MANUELL_BEGRUENDUNG)
        else:
            scope.clear_override(befund_id)
        session.commit()
        return _befund_antwort(request, user, scope, dossier_id, pruefung_id, befund_id)
    except NotFoundError:
        return _render(request, "nicht_gefunden.html", user=user, status_code=404)


MSG_ERGEBNIS = "Bitte wählen Sie ein gültiges Ergebnis."
MSG_NUR_MANUELL = "Nur manuell zu prüfende Befunde lassen sich abhaken."
MSG_PDF = "Der PDF-Export ist erst nach abgeschlossener Prüfung möglich."


@web_router.post(
    "/dossiers/{dossier_id}/pruefungen/{pruefung_id}/befunde/{befund_id}/{aktion}",
    response_model=None,
)
async def befund_aktion(
    request: Request,
    dossier_id: uuid.UUID,
    pruefung_id: uuid.UUID,
    befund_id: uuid.UUID,
    aktion: str,
    user: Annotated[User | None, Depends(_optional_user)],
    session: Session = Depends(get_session),
) -> Response:
    if aktion not in {"override", "bestaetigen", "zuruecksetzen"}:
        return _render(request, "nicht_gefunden.html", user=user, status_code=404)
    return await _befund_aktion(request, dossier_id, pruefung_id, befund_id, user, session, aktion)
