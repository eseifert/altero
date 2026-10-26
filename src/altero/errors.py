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


class MissingObjectError(AlteroError):
    """A write names another object it depends on, and that object does not exist.

    A parent item, a parent collection, or a collection an item is filed in.
    Distinct from :class:`NotFoundError`, which is about the object addressed:
    a client holding the dependency can upload it and try again, and ``data``
    names it so that it can. ``data`` uses the property the write named it by.
    """

    def __init__(self, message: str, **data: str) -> None:
        super().__init__(message)
        self.data = data


class InvalidParentError(AlteroError):
    """A note or attachment names a parent it cannot have: a note or attachment.

    Upstream's 409 for it carries the parent in ``data``, as a missing one
    does; the desktop, finding that parent present, leaves it at that.
    """

    def __init__(self, message: str, **data: str) -> None:
        super().__init__(message)
        self.data = data


class ConfirmationRequiredError(AlteroError):
    """A change would throw something away that the request did not agree to.

    ``data`` says what, so that the caller can ask the person and send the
    same request again with their answer.
    """

    def __init__(self, message: str, **data: object) -> None:
        super().__init__(message)
        self.data = data


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
