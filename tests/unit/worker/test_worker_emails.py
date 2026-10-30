"""The alert email, with Resend's send swapped for a fake. Nothing leaves."""
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

ALERT = SimpleNamespace(
    alert_id=7,
    email="ada@example.com",
    symbol="NVDA",
    direction="above",
    threshold=Decimal("100.0"),
    triggered_price=Decimal("102.5"),
    triggered_at=datetime(2024, 1, 1, 12, 0, 5, tzinfo=UTC),
)


@pytest.fixture
def outbox(worker_emails, monkeypatch):
    """Every email handed to Resend lands here; `error` makes Resend raise."""
    outbox = SimpleNamespace(sent=[], error=None)

    def send(params):
        if outbox.error:
            raise outbox.error
        outbox.sent.append(params)
        return {"id": "msg_1"}

    monkeypatch.setattr(worker_emails.resend.Emails, "send", send)
    # send_alert_triggered sets the module-wide key; put the old one back.
    monkeypatch.setattr(worker_emails.resend, "api_key", None)
    return outbox


def test_no_key_means_no_email(worker_emails, outbox):
    result = worker_emails.send_alert_triggered(None, ALERT)

    assert result == {"success": False, "error": "RESEND_API_KEY not configured"}
    assert outbox.sent == []


def test_the_email_goes_to_the_alerts_owner(worker_emails, outbox):
    result = worker_emails.send_alert_triggered("test-key", ALERT)

    assert result == {"success": True, "message_id": "msg_1"}
    [email] = outbox.sent
    assert email["from"] == worker_emails.SENDER
    assert email["to"] == ["ada@example.com"]
    assert email["subject"] == "Alert triggered: NVDA above 100.0"


def test_the_email_says_what_price_fired_it_and_when(worker_emails, outbox):
    worker_emails.send_alert_triggered("test-key", ALERT)

    html = outbox.sent[0]["html"]
    assert "Price above 100.0" in html
    assert "102.5" in html
    assert "2024-01-01 12:00 UTC" in html


def test_a_resend_error_comes_back_as_a_failure(worker_emails, outbox):
    outbox.error = ConnectionError("Resend is down")

    result = worker_emails.send_alert_triggered("test-key", ALERT)

    assert result == {"success": False, "error": "Resend is down"}
