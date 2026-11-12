"""Current administrators review verified applicants without reading libraries."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from altero.api.deps import SessionDep
from altero.api.local_auth import SsoOnlyDep
from altero.api.routes.web import AuthenticatedDep, CsrfDep
from altero.api.routes.webadmin import AdministratorDep
from altero.api.routes.webregistration import _policy
from altero.services import account, registrationadmission, registrations

router = APIRouter(prefix="/web/admin/registrations", tags=["web"])


class Decision(BaseModel):
    current_password: str | None = Field(default=None, alias="currentPassword")


@router.get("")
async def queue(
    request: Request,
    session: SessionDep,
    actor: AdministratorDep,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Response:
    _policy(request)
    rows = await registrations.review_queue(
        session, actor_id=actor.id, after_id=after_id, limit=limit
    )
    return JSONResponse(
        {
            "requests": [
                {
                    "id": r.id,
                    "username": r.username,
                    "email": r.email,
                    "displayName": r.display_name,
                    "created": r.created.isoformat() + "Z",
                    "expires": r.expires.isoformat() + "Z",
                }
                for r in rows
            ]
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{request_id}/approve", status_code=204)
async def approve(
    request: Request,
    session: SessionDep,
    actor: AdministratorDep,
    browser: AuthenticatedDep,
    sso_only: SsoOnlyDep,
    body: Decision,
    request_id: int,
    _csrf: CsrfDep,
) -> Response:
    policy = _policy(request)
    await account.require_proof(
        session, actor, browser, password=body.current_password, sso_only=sso_only
    )
    actor_id = actor.id
    if not await registrationadmission.approve(
        session, request_id, actor_id=actor_id, policy=policy
    ):
        raise HTTPException(409, "The application can no longer be approved")
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/{request_id}/reject", status_code=204)
async def reject(
    request: Request,
    session: SessionDep,
    actor: AdministratorDep,
    request_id: int,
    _csrf: CsrfDep,
) -> Response:
    _policy(request)
    if not await registrations.reject(session, request_id, actor_id=actor.id):
        raise HTTPException(409, "The application can no longer be rejected")
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
