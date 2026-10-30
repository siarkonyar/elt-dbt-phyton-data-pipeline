from notify import queue_alert_emails

# Spelled out, not imported: the worker finds its function by this exact
# name, so a typo in notify.py has to fail here.
WORKER_TASK_NAME = "tasks.send_alert_email"


class RecordingApp:
    """Stands in for the Celery app. Keeps every send_task call instead of
    pushing it into Redis."""

    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def send_task(self, name, args):
        self.calls.append((name, args))
        if self.error:
            raise self.error


def test_each_fired_alert_becomes_its_own_task():
    """One task per alert, so one failed email never holds back the rest."""
    app = RecordingApp()

    assert queue_alert_emails(app, [7, 9]) is True

    assert app.calls == [(WORKER_TASK_NAME, [7]), (WORKER_TASK_NAME, [9])]


def test_nothing_is_queued_when_no_alert_fired():
    """Most flushes fire nothing, and check_alerts hands back an empty list."""
    app = RecordingApp()

    assert queue_alert_emails(app, []) is False
    assert app.calls == []


def test_a_down_broker_is_logged_and_never_raised(capsys):
    """The alerts are already marked as fired. A down Redis must not take the
    stream down with it."""
    app = RecordingApp(error=ConnectionError("redis is down"))

    assert queue_alert_emails(app, [7]) is False
    assert "alert email not queued" in capsys.readouterr().err
