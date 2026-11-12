"""Applicant status and cancellation, separate from account authentication.

Public submission acknowledges generically; a mailbox proof creates only an
applicant credential. Account creation requires a separate administrator decision.
"""

import hmac
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.api.deps import SessionDep
from altero.api.local_auth import require_local_auth
from altero.api.routes.web import _client_address
from altero.services import (
    passwords,
    registrationaccess,
    registrationadmission,
    registrationflow,
    registrationlimits,
    webauth,
)
from altero.services.registrationaccess import ApplicantStatus
from altero.services.registrationpolicy import RegistrationPolicy

router = APIRouter(prefix="/web/registration", tags=["web"])
COOKIE = "altero_applicant"
CSRF_COOKIE = "altero_applicant_csrf"
COOKIE_PATH = "/web/registration"


def _policy(request: Request) -> RegistrationPolicy:
    settings = request.app.state.settings
    if not settings.registration_approval:
        raise HTTPException(403, "Verified registration is not enabled")
    return RegistrationPolicy(settings, allowed_domains=tuple(settings.registration_domains))


class Application(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=320)
    display_name: str = Field(default="", alias="displayName", max_length=255)


class MailboxProof(BaseModel):
    token: str = Field(min_length=32, max_length=128)


class Enrollment(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


def _set_applicant(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path=COOKIE_PATH,
        max_age=int(registrationaccess.LIFETIME.total_seconds()),
    )


@router.post("/apply", status_code=202, dependencies=[Depends(require_local_auth)])
async def apply(request: Request, session: SessionDep, body: Application) -> Response:
    policy = _policy(request)
    settings = request.app.state.settings
    recipient = policy.address(body.email)
    allowed = not await webauth.no_accounts_yet(session) and await webauth.registration_open(
        session, allow=settings.open_registration, email=recipient
    )
    await registrationflow.submit(
        session,
        username=body.username,
        email=recipient,
        display_name=body.display_name,
        policy=policy,
        public_url=settings.public_url,
        send=request.app.state.mailer.send,
        address=_client_address(request),
        allowed=allowed,
        max_pending=settings.registration_max_pending,
        ip_limit=settings.registration_ip_limit,
        global_limit=settings.registration_global_limit,
    )
    return JSONResponse(
        {"message": "If these details can be used, an email will explain the next step."},
        status_code=202,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/verify", dependencies=[Depends(require_local_auth)])
async def verify(request: Request, session: SessionDep, body: MailboxProof) -> Response:
    policy = _policy(request)
    await registrationlimits.reserve(
        session,
        registrationlimits.Budget(
            "registration-verify-address-hour", _client_address(request), 20, timedelta(hours=1)
        ),
    )
    token = await registrationaccess.claim_mailbox(session, body.token, policy=policy)
    if token is None:
        raise HTTPException(400, "This registration link is invalid or expired")
    response = JSONResponse({"verified": True}, headers={"Cache-Control": "no-store"})
    _set_applicant(response, request, token)
    return response


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


@router.post("/resend", status_code=202, dependencies=[Depends(require_local_auth)])
async def resend(request: Request, session: SessionDep, _csrf: CsrfDep) -> Response:
    settings = request.app.state.settings
    await registrationflow.resend(
        session,
        request.cookies.get(COOKIE, ""),
        policy=_policy(request),
        public_url=settings.public_url,
        send=request.app.state.mailer.send,
        address=_client_address(request),
        ip_limit=settings.registration_ip_limit,
        global_limit=settings.registration_global_limit,
    )
    return JSONResponse(
        {"message": "If this request can be resumed, a new link will be emailed."},
        status_code=202,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/enroll", dependencies=[Depends(require_local_auth)])
async def enroll(
    request: Request, session: SessionDep, body: Enrollment, _csrf: CsrfDep
) -> Response:
    token = request.cookies.get(COOKIE, "")
    await registrationlimits.reserve(
        session,
        registrationlimits.Budget(
            "registration-enroll-address-hour", _client_address(request), 20, timedelta(hours=1)
        ),
        registrationlimits.Budget("registration-enroll-token-hour", token, 5, timedelta(hours=1)),
    )
    if not await registrationadmission.enroll(
        session,
        token,
        body.password,
        policy=passwords.PasswordPolicy.from_settings(request.app.state.settings),
    ):
        raise HTTPException(409, "This application is not available for password enrollment")
    response = JSONResponse({"enrolled": True}, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response
