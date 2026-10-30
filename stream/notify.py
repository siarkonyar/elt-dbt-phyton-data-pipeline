import sys

from celery import Celery

SEND_ALERT_EMAIL = "tasks.send_alert_email"

def connect_broker(broker_url):
  return Celery("stream", broker=broker_url)

#app is given as an input for test to give a fake app
def queue_alert_emails(app, alert_ids):
  if not alert_ids:
    return False

  try:
    for alert_id in alert_ids:
      app.send_task(SEND_ALERT_EMAIL, args=[alert_id])
  except Exception as error:
    print("alert email not queued:", error, file=sys.stderr)
    return False

  return True
