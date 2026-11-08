"""The browser's authentication policy; sync credentials are independent."""

from typing import Annotated

from fastapi import Depends
from starlette.requests import Request

from altero.errors import ForbiddenError


def sso_only(request: Request) -> bool:
    return request.app.state.settings.sso_only


SsoOnlyDep = Annotated[bool, Depends(sso_only)]


def require_local_auth(sso_only: SsoOnlyDep) -> None:
    if sso_only:
        raise ForbiddenError("Local authentication is disabled; use single sign-on")
