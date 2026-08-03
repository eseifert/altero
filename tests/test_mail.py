"""Delivery of the few messages altero sends.

There are two senders and the choice between them is a deployment fact, not a
behaviour: with a relay configured a message goes out over SMTP, and without
one it is written to the log. A self-hosted instance frequently has no relay,
and the owner of a fresh container still has to be able to finish registering,
so the log is a delivery channel here rather than an error path.
"""

import logging

import pytest

from altero.services import mail
from altero.settings import Settings


def message() -> mail.Message:
    return mail.Message(
        to="ada@example.org",
        subject="Confirm your address",
        body="Follow this link: https://altero.example/app/verify?token=abc",
    )


class TestChoosingASender:
    def test_no_relay_configured_gives_the_logging_sender(self) -> None:
        assert isinstance(mail.build_mailer(Settings()), mail.LoggingMailer)

    def test_a_configured_relay_gives_the_smtp_sender(self) -> None:
        settings = Settings(smtp_url="smtp://mail.example.org:587")

        assert isinstance(mail.build_mailer(settings), mail.SmtpMailer)


class TestTheLoggingSender:
    async def test_it_writes_the_whole_body_including_the_link(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The link is the point: it is how someone finishes registering."""
        with caplog.at_level(logging.WARNING, logger="altero.mail"):
            await mail.LoggingMailer().send(message())

        assert "ada@example.org" in caplog.text
        assert "https://altero.example/app/verify?token=abc" in caplog.text

    async def test_it_says_why_it_is_logging_rather_than_sending(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Otherwise this reads like a leak rather than a fallback."""
        with caplog.at_level(logging.WARNING, logger="altero.mail"):
            await mail.LoggingMailer().send(message())

        assert "smtp" in caplog.text.lower()

    async def test_it_reports_having_delivered_nothing(self) -> None:
        """The caller records whether a notification actually went anywhere."""
        assert await mail.LoggingMailer().send(message()) is False


class TestTheSmtpSender:
    def test_it_reads_host_port_and_credentials_from_the_url(self) -> None:
        sender = mail.SmtpMailer(
            mail.SmtpConfig.from_url("smtps://ada:secret@mail.example.org:465"),
            sender="altero@example.org",
        )

        assert sender.config.host == "mail.example.org"
        assert sender.config.port == 465
        assert sender.config.username == "ada"
        assert sender.config.password == "secret"
        assert sender.config.implicit_tls is True

    def test_plain_smtp_defaults_to_the_submission_port(self) -> None:
        config = mail.SmtpConfig.from_url("smtp://mail.example.org")

        assert config.port == 587
        assert config.implicit_tls is False

    def test_a_url_without_credentials_is_fine(self) -> None:
        config = mail.SmtpConfig.from_url("smtp://mail.example.org:25")

        assert config.username is None
        assert config.password is None

    def test_an_unusable_url_is_refused_at_construction(self) -> None:
        """Configuration is checked when it is read, not on the first send."""
        with pytest.raises(ValueError, match="smtp"):
            mail.SmtpConfig.from_url("https://mail.example.org")

    def test_a_url_with_no_host_is_refused(self) -> None:
        with pytest.raises(ValueError, match="host"):
            mail.SmtpConfig.from_url("smtp://")

    async def test_a_failure_to_send_is_reported_not_raised(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dead relay must not turn changing a password into a 500.

        The account change has already happened; the notification about it is
        the less important half, and losing it is not a reason to fail the
        request that caused it.
        """
        sender = mail.SmtpMailer(
            mail.SmtpConfig.from_url("smtp://mail.example.org"), sender="altero@example.org"
        )

        def explode(_: mail.Message) -> None:
            raise OSError("Connection refused")

        monkeypatch.setattr(sender, "_deliver", explode)

        with caplog.at_level(logging.ERROR, logger="altero.mail"):
            delivered = await sender.send(message())

        assert delivered is False
        assert "Connection refused" in caplog.text

    def test_the_message_carries_a_from_address_and_a_subject(self) -> None:
        sender = mail.SmtpMailer(
            mail.SmtpConfig.from_url("smtp://mail.example.org"), sender="altero@example.org"
        )

        built = sender.build(message())

        assert built["From"] == "altero@example.org"
        assert built["To"] == "ada@example.org"
        assert built["Subject"] == "Confirm your address"
        assert "https://altero.example/app/verify?token=abc" in built.get_content()

    def test_a_subject_with_a_newline_cannot_inject_a_header(self) -> None:
        """A display name reaches this; a bare join would let it forge headers."""
        sender = mail.SmtpMailer(
            mail.SmtpConfig.from_url("smtp://mail.example.org"), sender="altero@example.org"
        )
        nasty = mail.Message(
            to="ada@example.org",
            subject="Hello\r\nBcc: everyone@example.org",
            body="text",
        )

        built = sender.build(nasty)

        assert built["Bcc"] is None
        assert "\r\n" not in str(built["Subject"])
