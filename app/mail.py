"""E-Mail-Versand über SMTP (ADR 0005). Konfiguration nur über Umgebungsvariablen.

Mailinhalte (Empfänger, Links, Tokens) gelangen nie ins Log, nur Fehlercodes.
"""

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from app.config import Settings, get_settings
from app.logging_setup import log_event


class MailError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Mail:
    an: str
    betreff: str
    text: str


class Mailer(Protocol):
    def send(self, mail: Mail) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, mail: Mail) -> None:
        s = self.settings
        if not s.smtp_host or not s.mail_from:
            raise MailError("MAIL_NOT_CONFIGURED")
        msg = EmailMessage()
        msg["From"] = s.mail_from
        msg["To"] = mail.an
        msg["Subject"] = mail.betreff
        msg.set_content(mail.text)
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
                if s.smtp_starttls:
                    smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError):
            raise MailError("MAIL_SEND_FAILED") from None


class FakeMailer:
    """Sammelt Mails im Speicher (Tests, lokale Entwicklung ohne SMTP)."""

    def __init__(self) -> None:
        self.outbox: list[Mail] = []

    def send(self, mail: Mail) -> None:
        self.outbox.append(mail)


def get_mailer() -> Mailer:
    """FastAPI-Dependency; Tests überschreiben sie mit `FakeMailer`."""
    return SmtpMailer(get_settings())


def send_safely(mailer: Mailer, mail: Mail) -> None:
    """Versand im Hintergrund: Fehler werden nur als Code geloggt."""
    try:
        mailer.send(mail)
    except MailError as exc:
        log_event("MAIL_FAILED", level=logging.ERROR, code=exc.code)
