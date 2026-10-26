"""What a browser may do with an answer.

One place runs script: the web interface under ``/app``, and only the script it
was built with. Everything else this server says is data -- an attachment, a
bibliography, the API's JSON -- and a browser can be sent to any of it as a
page: ``/file/view`` takes its API key in the query string, a shared link hands
out files with no key at all, and the web interface opens attachments in a
tab. A page there would run on this origin, beside the session cookie of
whoever opened it, so an HTML file somebody synced into a group could act as
every member who clicked on it.

So every answer outside the interface carries ``sandbox``: whatever it holds
runs no script and belongs to no origin. A PDF is the exception, because a
sandboxed document may not use a plugin and Chrome's PDF viewer is one -- the
reader would see a refusal instead of the paper. PDF viewers run a document's
own script apart from the page, if at all.

Plain ASGI, like the other middleware here, so a large download is not relayed
through a memory stream.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from altero.api.spa import MOUNT_PATH

#: The interface's own policy: its script, its styles and its fonts, all from
#: here. Style *attributes* are let in because a note and a bibliography carry
#: them -- colour, alignment, a hanging indent -- and both are cleaned before
#: they are shown; Vue's own style bindings go through the CSSOM, which no
#: policy governs. Images may be inline data, as a pasted image in a note is,
#: and nothing else from elsewhere: a note is somebody else's writing, and a
#: remote image in it would tell its author who read it and when.
INTERFACE_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "style-src-attr 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "worker-src 'self'",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
    ]
)

#: Every other answer: a document that runs nothing and has no origin.
DATA_POLICY = "sandbox"

#: Media types the sandbox would stop a browser from showing at all.
UNSANDBOXED = frozenset({"application/pdf"})


def _interface(path: str) -> bool:
    """Whether ``path`` is the interface. The root serves its page too."""
    return path in ("/", MOUNT_PATH) or path.startswith(f"{MOUNT_PATH}/")


class SecurityHeadersMiddleware:
    """Give every response the policy that fits what it is."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        interface = _interface(scope["path"])

        async def secured(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                # A browser guessing that a text file is HTML would undo the rest.
                headers["X-Content-Type-Options"] = "nosniff"
                media_type = headers.get("content-type", "").partition(";")[0].strip().lower()
                if interface:
                    headers["Content-Security-Policy"] = INTERFACE_POLICY
                elif media_type not in UNSANDBOXED:
                    headers["Content-Security-Policy"] = DATA_POLICY
            await send(message)

        await self.app(scope, receive, secured)
