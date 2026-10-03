from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates

from app.auth.users import (
    COOKIE_NAME,
    UserManager,
    cookie_backend,
    get_user_manager,
)
from app.config import get_settings
from app.db.models import User
from app.web import csrf

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

web_router = APIRouter(tags=["web"], include_in_schema=False)

MSG_LOGIN = "E-Mail oder Passwort ist falsch."
MSG_CSRF = "Die Sitzung des Formulars ist abgelaufen. Bitte versuchen Sie es erneut."


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
