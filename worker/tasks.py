from celery import Celery
import os

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/1")

app = Celery("worker", broker = CELERY_BROKER_URL)

@app.task
def send_alert_email(alert_id):
  print(alert_id)