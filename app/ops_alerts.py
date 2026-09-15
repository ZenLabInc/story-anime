"""Operational alert delivery for the YourStory service.

Alerts use the already configured SES SMTP sender.  The destination is a
Google Group so operational routing can be changed without a new deployment.
Never include authentication codes, API keys, or full request bodies here.
"""
import smtplib
import ssl
from email.message import EmailMessage

from app import settings


DEFAULT_ALERT_TO = ""


def _setting(name, default=""):
    return settings.get(name, default)


def notify(subject, body):
    """Send one operational alert, returning False when delivery is unavailable.

    Alerting must not make the original request fail again.  SMTP failures are
    therefore deliberately swallowed after the best-effort send.
    """
    host = _setting("SMTP_HOST")
    sender = _setting("SMTP_FROM")
    recipient = _setting("OPS_ALERT_TO", DEFAULT_ALERT_TO)
    if not host or not sender or not recipient:
        return False
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = f"[YourStory] {str(subject)[:160]}"
    message["Auto-Submitted"] = "auto-generated"
    message["X-YourStory-Alert"] = "1"
    message.set_content(str(body)[:12000])
    try:
        with smtplib.SMTP(host, int(_setting("SMTP_PORT", "587")), timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            user = _setting("SMTP_USER")
            if user:
                smtp.login(user, _setting("SMTP_PASSWORD"))
            smtp.send_message(message)
        return True
    except Exception:
        return False


def masked_email(value):
    """Keep operational logs useful without exposing a full user address."""
    value = str(value or "")
    if "@" not in value:
        return "(unknown)"
    local, domain = value.split("@", 1)
    return f"{(local[:1] or '*')}***@{domain}"
