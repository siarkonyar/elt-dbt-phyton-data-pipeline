import os
from functools import lru_cache

from celery import Celery
from celery.signals import worker_init
from celery.utils.log import get_task_logger

from db import apply_schema, get_engine, read_alert_to_email, record_notification
from emails import send_alert_triggered

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/1")

app = Celery("worker", broker=CELERY_BROKER_URL)
logger = get_task_logger(__name__)

MAX_RETRIES = 5
FIRST_RETRY_SECONDS = 30


def retry_countdown(retries):
    return FIRST_RETRY_SECONDS * 2**retries


@worker_init.connect
def create_tables(**kwargs):
    engine = get_engine()
    with engine.begin() as connection:
        apply_schema(connection)
    engine.dispose()


@lru_cache(maxsize=1)
def _engine():
    return get_engine()

@app.task(bind=True, name="tasks.send_alert_email", max_retries=MAX_RETRIES)
def send_alert_email(self, alert_id):
    with _engine().connect() as connection:
        alert = read_alert_to_email(connection, alert_id)

    if alert is None:
        logger.info("alert %s is gone or has not fired, nothing to send", alert_id)
        return "skipped"

    result = send_alert_triggered(os.environ.get("RESEND_API_KEY"), alert)

    with _engine().begin() as connection:
        record_notification(connection, alert_id, result)

    if result["success"]:
        logger.info("alert %s emailed, message id %s", alert_id, result["message_id"])
        return "sent"

    logger.warning("alert %s email failed: %s", alert_id, result["error"])
    if not result["retry"]:
        return "failed"

    raise self.retry(countdown=retry_countdown(self.request.retries))
