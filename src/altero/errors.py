"""Domain errors.

These carry no HTTP vocabulary. The API layer is responsible for mapping them
onto status codes, which keeps the service layer independent of the web
framework.
"""


class AlteroError(Exception):
    """Base class for errors raised by the service layer."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(AlteroError):
    """The requested object does not exist."""


class ForbiddenError(AlteroError):
    """The credential does not grant the required access."""


class InvalidInputError(AlteroError):
    """The request data is malformed or violates the schema."""
