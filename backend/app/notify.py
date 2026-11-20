"""Outgoing messages. Routes depend on `get_outbox`, so tests and other providers can swap it."""

import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger("freightflow.notify")


class Outbox:
    def email(self, to: str, subject: str, body: str) -> None:
        settings = get_settings()
        if settings.smtp_host is None:
            log.warning("No SMTP host configured. Email to %s not sent. Subject: %s\n%s", to, subject, body)
            return
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = settings.smtp_from, to, subject
        message.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password or "")
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError):
            # Runs after the response has gone out; the person can ask for another code.
            log.exception("Could not send email to %s", to)

    def sms(self, to: str, body: str) -> bool:
        """Send a text message; True if it went out. No provider is chosen yet: subclass and override."""
        log.warning("No SMS provider configured. SMS to %s not sent:\n%s", to, body)
        return False

    def whatsapp(self, to: str, body: str) -> bool:
        """Send a WhatsApp message; True if it went out. No provider is chosen yet: subclass and override."""
        log.warning("No WhatsApp provider configured. Message to %s not sent:\n%s", to, body)
        return False


_outbox = Outbox()


def get_outbox() -> Outbox:
    return _outbox
