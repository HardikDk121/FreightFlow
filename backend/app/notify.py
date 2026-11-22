"""Outgoing messages. Routes depend on `get_outbox`, so tests and other providers can swap it."""

import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger("freightflow.notify")


def _mask(address: str) -> str:
    """Enough of an address or number to tell messages apart in the log, not to contact anyone."""
    return address[:3] + "***" + address[-2:] if len(address) > 6 else "***"


def _body(body: str) -> str:
    """Message text goes to the log only in development: it can hold reset codes and amounts."""
    return f"\n{body}" if get_settings().env == "development" else ""


class Outbox:
    def email(self, to: str, subject: str, body: str, attachments: list[tuple[str, bytes, str]] | None = None) -> None:
        """`attachments` are (file name, content, MIME type), for example a scheduled report."""
        settings = get_settings()
        if settings.smtp_host is None:
            log.warning("No SMTP host configured. Email to %s not sent. Subject: %s%s", _mask(to), subject, _body(body))
            return
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = settings.smtp_from, to, subject
        message.set_content(body)
        for name, content, mime in attachments or ():
            main, sub = mime.split("/", 1)
            message.add_attachment(content, maintype=main, subtype=sub, filename=name)
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
        log.warning("No SMS provider configured. SMS to %s not sent.%s", _mask(to), _body(body))
        return False

    def whatsapp(self, to: str, body: str) -> bool:
        """Send a WhatsApp message; True if it went out. No provider is chosen yet: subclass and override."""
        log.warning("No WhatsApp provider configured. Message to %s not sent.%s", _mask(to), _body(body))
        return False


_outbox = Outbox()


def get_outbox() -> Outbox:
    return _outbox
