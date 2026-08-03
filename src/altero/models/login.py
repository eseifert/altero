"""Login sessions.

The desktop client obtains its API key by starting a session, sending the user
to a page to authenticate, then polling until the session completes. Upstream
authenticates that page against zotero.org; here it is approved from the
command line instead.

Not to be confused with :class:`~altero.models.webauth.WebSession`, which is a
person's browser session in the web interface. This one exists to hand an API
key to a desktop client, and the two do not currently meet: signing in to the
interface does not approve a pending client login.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from altero.db import Base


class LoginSession(Base):
    """A pending, completed or cancelled login."""

    __tablename__ = "login_sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: One of pending, completed or cancelled, as the client's poll expects.
    status: Mapped[str] = mapped_column(String(16), default="pending")
    #: The user id the client already knows, when it is re-authenticating.
    requested_user_id: Mapped[int | None] = mapped_column()
    #: Set once approved: the key handed to the client.
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("api_keys.id"))
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
