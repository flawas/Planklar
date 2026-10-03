from celery import Celery

from app.config import get_settings

_redis_url = get_settings().redis_url

celery_app = Celery("planklar", broker=_redis_url, backend=_redis_url)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]


@celery_app.task(name="planklar.ping")
def ping() -> str:
    return "pong"
