"""The worker's task, with Postgres and Resend swapped for fakes.

tasks.py is loaded by file path (worker_tasks in conftest.py), so the fakes
are put on that loaded module with monkeypatch. Calling the task directly runs
it right here, with no broker and no worker process.
"""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from celery.exceptions import MaxRetriesExceededError

# The stream queues the task by this exact name (stream/notify.py). Spelled
# out here so a rename on either side fails a test instead of losing emails.
STREAM_TASK_NAME = "tasks.send_alert_email"

ALERT = SimpleNamespace(alert_id=7, email="ada@example.com")

SENT = {"success": True, "message_id": "msg_1"}
RESEND_DOWN = {"success": False, "error": "Resend is down", "retry": True}
REJECTED = {"success": False, "error": "Invalid `to` field", "retry": False}


class FakeEngine:
    """Hands out one shared stand-in connection, for reads and writes alike."""

    connection = object()

    def connect(self):
        return nullcontext(self.connection)

    def begin(self):
        return nullcontext(self.connection)


@pytest.fixture
def fakes(worker_tasks, monkeypatch):
    """Records what the task read and sent. Tests change alert/result first;
    `results` lines up one answer per try, after which `result` repeats."""
    fakes = SimpleNamespace(
        alert=ALERT, result=SENT, results=[], read=[], sent=[], recorded=[]
    )

    def read_alert_to_email(connection, alert_id):
        fakes.read.append(alert_id)
        return fakes.alert

    def send_alert_triggered(api_key, alert):
        fakes.sent.append((api_key, alert))
        return fakes.results.pop(0) if fakes.results else fakes.result

    def record_notification(connection, alert_id, result):
        fakes.recorded.append((alert_id, result))

    monkeypatch.setattr(worker_tasks, "_engine", FakeEngine)
    monkeypatch.setattr(worker_tasks, "read_alert_to_email", read_alert_to_email)
    monkeypatch.setattr(worker_tasks, "send_alert_triggered", send_alert_triggered)
    monkeypatch.setattr(worker_tasks, "record_notification", record_notification)
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    return fakes


def test_the_task_name_matches_what_the_stream_queues(worker_tasks):
    assert worker_tasks.send_alert_email.name == STREAM_TASK_NAME


def test_a_fired_alert_is_emailed_to_its_owner(worker_tasks, fakes):
    assert worker_tasks.send_alert_email(7) == "sent"

    assert fakes.read == [7]
    assert fakes.sent == [("test-key", ALERT)]


def test_a_gone_or_unfired_alert_is_skipped_without_an_email(worker_tasks, fakes):
    fakes.alert = None

    assert worker_tasks.send_alert_email(7) == "skipped"
    assert fakes.sent == []


def test_a_rejected_email_fails_without_a_retry(worker_tasks, fakes):
    fakes.result = REJECTED

    assert worker_tasks.send_alert_email(7) == "failed"
    assert len(fakes.sent) == 1


def test_a_sent_email_is_recorded(worker_tasks, fakes):
    worker_tasks.send_alert_email(7)

    assert fakes.recorded == [(7, SENT)]


def test_a_rejected_email_is_recorded_too(worker_tasks, fakes):
    fakes.result = REJECTED

    worker_tasks.send_alert_email(7)

    assert fakes.recorded == [(7, REJECTED)]


# .apply() runs the task here the way a worker would, retries included: each
# retry runs straight away instead of after its countdown.


def test_a_temporary_failure_is_retried_until_the_email_goes_out(
    worker_tasks, fakes
):
    fakes.results = [RESEND_DOWN, SENT]

    outcome = worker_tasks.send_alert_email.apply(args=[7])

    assert outcome.get() == "sent"
    assert len(fakes.sent) == 2
    assert fakes.recorded == [(7, RESEND_DOWN), (7, SENT)]


def test_the_task_gives_up_after_the_last_retry(worker_tasks, fakes):
    fakes.result = RESEND_DOWN

    outcome = worker_tasks.send_alert_email.apply(args=[7])

    assert outcome.failed()
    assert isinstance(outcome.result, MaxRetriesExceededError)
    assert len(fakes.sent) == worker_tasks.MAX_RETRIES + 1
    assert len(fakes.recorded) == worker_tasks.MAX_RETRIES + 1


def test_each_wait_is_twice_the_last(worker_tasks):
    waits = [worker_tasks.retry_countdown(retries) for retries in range(5)]

    assert waits == [30, 60, 120, 240, 480]


def test_a_skipped_alert_records_nothing(worker_tasks, fakes):
    fakes.alert = None

    worker_tasks.send_alert_email(7)

    assert fakes.recorded == []


def test_the_worker_creates_its_table_and_lets_go_of_the_engine(
    worker_tasks, monkeypatch
):
    """Runs once in the main worker process, before it forks its children.
    Disposing the engine means no open connection gets copied into them."""
    engine = FakeEngine()
    engine.disposed = False

    def dispose():
        engine.disposed = True

    engine.dispose = dispose
    applied = []
    monkeypatch.setattr(worker_tasks, "get_engine", lambda: engine)
    monkeypatch.setattr(worker_tasks, "apply_schema", applied.append)

    worker_tasks.create_tables()

    assert applied == [FakeEngine.connection]
    assert engine.disposed


def test_the_engine_is_built_once_and_then_reused(worker_tasks, monkeypatch):
    """Built on the first call, not at import - and never again after."""
    built = []
    monkeypatch.setattr(worker_tasks, "get_engine", lambda: built.append(1))
    worker_tasks._engine.cache_clear()

    worker_tasks._engine()
    worker_tasks._engine()

    worker_tasks._engine.cache_clear()
    assert len(built) == 1
