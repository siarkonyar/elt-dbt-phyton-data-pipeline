import resend
from resend.exceptions import ApplicationError, RateLimitError

SENDER = "onboarding@resend.dev"

#these are the only legit reasons to retry a task
TEMPORARY_ERRORS = (ApplicationError, RateLimitError, RuntimeError)


def send_alert_triggered(resend_api_key, alert):
    if not resend_api_key:
        return {
            "success": False,
            "error": "RESEND_API_KEY not configured",
            "retry": False,
        }

    resend.api_key = resend_api_key

    subject = f"Alert triggered: {alert.symbol} {alert.direction} {alert.threshold}"
    html = f"""
    <h2>Price Alert Triggered</h2>
    <p>Your alert for <strong>{alert.symbol}</strong> has been triggered.</p>
    <ul>
        <li><strong>Condition:</strong> Price {alert.direction} {alert.threshold}</li>
        <li><strong>Triggered Price:</strong> {alert.triggered_price}</li>
        <li><strong>Triggered at:</strong> {alert.triggered_at:%Y-%m-%d %H:%M} UTC</li>
    </ul>
    <p>Log in to your dashboard to manage this alert.</p>
    """

    try:
        response = resend.Emails.send({
            "from": SENDER,
            "to": [alert.email],
            "subject": subject,
            "html": html,
        })
        return {"success": True, "message_id": response["id"]}
    except Exception as error:
        return {
            "success": False,
            "error": str(error),
            "retry": isinstance(error, TEMPORARY_ERRORS),
        }
