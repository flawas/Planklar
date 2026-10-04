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
