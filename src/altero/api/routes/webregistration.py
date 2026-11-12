"""Applicant status and cancellation, separate from account authentication.

No application creation, token issuance or mail delivery is exposed here.
"""

import hmac
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.api.deps import SessionDep
from altero.services import registrationaccess
from altero.services.registrationaccess import ApplicantStatus

router = APIRouter(prefix="/web/registration", tags=["web"])
COOKIE = "altero_applicant"
CSRF_COOKIE = "altero_applicant_csrf"
COOKIE_PATH = "/web/registration"


def _csrf(token: str) -> str:
    return hmac.digest(token.encode(), b"altero applicant csrf", "sha256").hex()


async def require_applicant(request: Request, session: SessionDep) -> ApplicantStatus:
    result = await registrationaccess.status(session, request.cookies.get(COOKIE))
    if result is None:
        raise HTTPException(401, "A valid applicant credential is required")
    return result


ApplicantDep = Annotated[ApplicantStatus, Depends(require_applicant)]


def require_csrf(request: Request, _applicant: ApplicantDep) -> None:
    expected = _csrf(request.cookies.get(COOKIE, "")).encode()
    cookie = request.cookies.get(CSRF_COOKIE, "").encode()
    header = request.headers.get("X-CSRF-Token", "").encode()
    if not secrets.compare_digest(expected, cookie) or not secrets.compare_digest(expected, header):
        raise HTTPException(403, "Missing or invalid applicant CSRF token")


CsrfDep = Annotated[None, Depends(require_csrf)]


@router.get("")
async def status(request: Request, applicant: ApplicantDep) -> Response:
    response = JSONResponse(
        {
            "requestID": applicant.request_id,
            "status": applicant.status.value,
            "expires": applicant.expires.isoformat() + "Z",
        },
        headers={"Cache-Control": "no-store"},
    )
    response.set_cookie(
        CSRF_COOKIE,
        _csrf(request.cookies[COOKIE]),
        httponly=False,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
        max_age=int(registrationaccess.LIFETIME.total_seconds()),
    )
    return response


@router.post("/cancel", status_code=204)
async def cancel(request: Request, session: SessionDep, _csrf: CsrfDep) -> Response:
    if not await registrationaccess.cancel(session, request.cookies.get(COOKIE)):
        raise HTTPException(409, "The application can no longer be cancelled")
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/logout", status_code=204)
async def logout(request: Request, session: SessionDep, _csrf: CsrfDep) -> Response:
    await registrationaccess.revoke(session, request.cookies.get(COOKIE))
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response
