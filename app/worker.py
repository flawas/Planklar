from celery import Celery

from app.config import get_settings

_redis_url = get_settings().redis_url

celery_app = Celery("liquet", broker=_redis_url, backend=_redis_url)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]


@celery_app.task(name="liquet.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="liquet.pruefung.run")
def run_pruefung_task(buero_id: str, pruefung_id: str) -> str:
    """Prüflauf ausführen (dünne Hülle um `app.dossiers.pruefung.run_pruefung`)."""
    import uuid

    from app.db.session import get_sessionmaker
    from app.dossiers.pruefung import run_pruefung
    from app.dossiers.scope import BueroScope
    from app.dossiers.service import get_storage

    with get_sessionmaker()() as session:
        scope = BueroScope(session, uuid.UUID(buero_id))
        return run_pruefung(scope, get_storage(), uuid.UUID(pruefung_id)).status.value
