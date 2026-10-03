from app.config import Settings


def ensure_oidc_disabled(settings: Settings) -> None:
    """OIDC ist vorbereitet (Konfigurationsschalter), aber noch nicht umgesetzt.

    Bei aktiviertem Schalter schlägt der Start laut fehl, statt stillschweigend
    ohne SSO zu laufen. Die Umsetzung hängt später als zusätzlicher Router und
    zusätzliche Auth-Strategie in `app.auth.users` ein.
    """
    if settings.oidc_enabled:
        raise RuntimeError("OIDC_ENABLED=true, aber die OIDC-Anbindung ist noch nicht umgesetzt")
