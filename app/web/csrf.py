import hmac
import secrets

from app.auth.users import get_auth_secret

CSRF_COOKIE = "liquet_csrf"


def _sign(nonce: str) -> str:
    return hmac.new(get_auth_secret().encode(), nonce.encode(), "sha256").hexdigest()


def new_token() -> str:
    nonce = secrets.token_urlsafe(24)
    return f"{nonce}.{_sign(nonce)}"


def is_valid(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    nonce, _, signature = token.partition(".")
    return hmac.compare_digest(signature, _sign(nonce))


def matches(cookie_token: str | None, form_token: str | None) -> bool:
    """Double-Submit-Cookie: Formularwert muss dem signierten Cookie entsprechen."""
    return (
        is_valid(cookie_token)
        and form_token is not None
        and hmac.compare_digest(cookie_token or "", form_token)
    )
