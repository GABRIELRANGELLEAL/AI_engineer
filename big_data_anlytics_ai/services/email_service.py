"""Email delivery (mock in development)."""

import logging
import smtplib
from email.message import EmailMessage

from config import get_settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    settings = get_settings()

    if settings.email_mock or not settings.smtp_host:
        logger.info(
            "[EMAIL MOCK] to=%s subject=%s\n%s",
            to,
            subject,
            body,
        )
        print(f"\n[EMAIL MOCK] To: {to}\nSubject: {subject}\n{body}\n")
        return

    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
