"""Sending the few messages altero produces.

Two senders. With a relay configured, SMTP; without one, the message is written
to the log. That second one is a delivery channel rather than a failure: a
self-hosted instance often has no relay at all, and whoever just deployed a
container still has to be able to read the confirmation link and finish
registering. `docker compose logs` is a reasonable place to find it, and the
same code path runs either way, so the one that works when mail is broken is
not a path that only ever runs when something is already wrong.

Nothing here raises on a delivery failure. Every message this module sends is
*about* something that has already happened -- an address to confirm, a
password that has changed -- so failing the request that caused it would undo
nothing and lose the change instead.
"""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import unquote, urlsplit

from altero.settings import Settings

logger = logging.getLogger("altero.mail")

#: Ports assumed when the URL does not name one. 587 is submission with
#: STARTTLS; 465 is SMTP wrapped in TLS from the first byte.
SUBMISSION_PORT = 587
IMPLICIT_TLS_PORT = 465

#: How long to wait on a relay. Short: a request is waiting behind this.
TIMEOUT_SECONDS = 10


@dataclass(frozen=True, slots=True)
class Message:
    """One outgoing message, in plain text."""

    to: str
    subject: str
    body: str


class Mailer(Protocol):
    """Something that can attempt to deliver a message."""

    async def send(self, message: Message) -> bool:
        """Return whether the message was actually handed to a relay."""
        ...


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    """Where and how to reach a relay."""

    host: str
    port: int
    username: str | None = None
    password: str | None = None
    #: True for smtps:// -- TLS from the first byte, rather than STARTTLS.
    implicit_tls: bool = False

    @classmethod
    def from_url(cls, url: str) -> SmtpConfig:
        """Parse ``smtp://`` or ``smtps://[user:password@]host[:port]``.

        Validated here, when the configuration is read, rather than on the
        first attempt to send: a typo in a URL should be visible at start-up
        and not when someone is waiting for a confirmation that never comes.
        """
        parts = urlsplit(url)
        if parts.scheme not in {"smtp", "smtps"}:
            raise ValueError(f"An smtp URL must begin with smtp:// or smtps://, not {url!r}")
        if not parts.hostname:
            raise ValueError(f"An smtp URL must name a host: {url!r}")

        implicit_tls = parts.scheme == "smtps"
        return cls(
            host=parts.hostname,
            port=parts.port or (IMPLICIT_TLS_PORT if implicit_tls else SUBMISSION_PORT),
            username=unquote(parts.username) if parts.username else None,
            password=unquote(parts.password) if parts.password else None,
            implicit_tls=implicit_tls,
        )


def _one_line(value: str) -> str:
    """Return ``value`` with anything that could end a header removed."""
    return " ".join(value.split())


class LoggingMailer:
    """Writes the message out instead of sending it.

    Used when no relay is configured. Says so explicitly, because a
    confirmation link appearing in a log with no explanation reads like a leak
    rather than the fallback it is.
    """

    async def send(self, message: Message) -> bool:
        logger.warning(
            "No SMTP relay is configured (set ALTERO_SMTP_URL), so this message "
            "was not sent. It is written out here instead.\n"
            "  To:      %s\n"
            "  Subject: %s\n"
            "%s",
            message.to,
            message.subject,
            message.body,
        )
        return False


class SmtpMailer:
    """Hands the message to an SMTP relay."""

    def __init__(self, config: SmtpConfig, *, sender: str) -> None:
        self.config = config
        self.sender = sender

    def build(self, message: Message) -> EmailMessage:
        """Render ``message`` as an email.

        Header values are flattened first. A display name reaches the subject,
        so a carriage return in one would otherwise end that header and begin
        another of the sender's choosing. ``EmailMessage`` does refuse such a
        value, but by raising -- which would turn a hostile display name into a
        failed request rather than a delivered notification about the very
        change that hostile name was set by.
        """
        built = EmailMessage()
        built["From"] = _one_line(self.sender)
        built["To"] = _one_line(message.to)
        built["Subject"] = _one_line(message.subject)
        built.set_content(message.body)
        return built

    def _deliver(self, message: Message) -> None:
        """Send synchronously. Called off the event loop by :meth:`send`."""
        built = self.build(message)
        client_class = smtplib.SMTP_SSL if self.config.implicit_tls else smtplib.SMTP
        with client_class(self.config.host, self.config.port, timeout=TIMEOUT_SECONDS) as client:
            if not self.config.implicit_tls:
                # Opportunistic: a relay on the local host commonly offers no
                # TLS at all, and refusing to use it would leave that
                # deployment unable to send anything.
                try:
                    client.starttls()
                except smtplib.SMTPNotSupportedError:
                    logger.warning(
                        "%s does not offer STARTTLS; sending in the clear", self.config.host
                    )
            if self.config.username is not None:
                client.login(self.config.username, self.config.password or "")
            client.send_message(built)

    async def send(self, message: Message) -> bool:
        # smtplib is blocking, and there is no async client in the standard
        # library. A thread keeps the event loop free without taking on a
        # dependency for something sent this rarely.
        try:
            await asyncio.to_thread(self._deliver, message)
        except (OSError, smtplib.SMTPException) as failure:
            logger.error("Could not send mail to %s: %s", message.to, failure)
            return False
        return True


def build_mailer(settings: Settings) -> Mailer:
    """Return the sender this deployment's configuration asks for."""
    if not settings.smtp_url:
        return LoggingMailer()
    return SmtpMailer(SmtpConfig.from_url(settings.smtp_url), sender=settings.mail_from)
