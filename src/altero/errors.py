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


class PreconditionFailedError(AlteroError):
    """The library changed since the version the client last saw."""


class PreconditionRequiredError(AlteroError):
    """The request needs a version precondition it did not supply."""


class RequestTooLargeError(AlteroError):
    """More objects were submitted than one request may carry."""


class OAuthError(AlteroError):
    """An OAuth 2.0 protocol error, named by the code RFC 6749 §5.2 defines.

    The code is protocol vocabulary rather than HTTP vocabulary: an OAuth client
    branches on ``error``, not on the status carrying it, and the registry of
    codes belongs to the protocol. So it lives here with the other domain
    errors, and :mod:`altero.api.errors` still decides which status reports it.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        #: One of the codes RFC 6749 §5.2 or RFC 6750 §3.1 defines --
        #: ``invalid_request``, ``invalid_client``, ``invalid_grant``,
        #: ``invalid_scope``, ``unauthorized_client``,
        #: ``unsupported_grant_type``, ``unsupported_response_type``.
        self.code = code
