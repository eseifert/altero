"""OAuth 2.0 and OpenID Connect API endpoints."""

import html
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Header, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select

from altero.api.deps import SessionDep, get_credential
from altero.errors import ForbiddenError, InvalidInputError
from altero.models.library import User
from altero.services import oauth, passwords, webauth

router = APIRouter(tags=["oauth"])


@router.get("/.well-known/openid-configuration")
async def openid_configuration(request: Request) -> dict:
    """Return OpenID Connect Discovery metadata."""
    base_url = str(request.base_url).rstrip("/")
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "userinfo_endpoint": f"{base_url}/oauth/userinfo",
        "revocation_endpoint": f"{base_url}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "scopes_supported": [
            "openid",
            "profile",
            "library.read",
            "library.write",
            "annotations.read",
            "annotations.write",
            "files.read",
        ],
    }


def render_login_page(
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    nonce: str | None = None,
    error_msg: str | None = None,
) -> HTMLResponse:
    """Render responsive Altero OAuth authorization and sign-in page."""
    error_html = (
        f'<div style="background:#450a0a;border:1px solid #991b1b;color:#fecaca;padding:10px 14px;border-radius:8px;font-size:13px;margin-bottom:16px;">{html.escape(error_msg)}</div>'
        if error_msg
        else ""
    )

    page_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>授权登录 - Altero</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      background: #090d16;
      color: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }}
    .auth-card {{
      background: #0f172a;
      border: 1px solid #1e293b;
      border-radius: 16px;
      width: 100%;
      max-width: 400px;
      padding: 28px 24px;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
    }}
    .logo {{
      font-size: 20px;
      font-weight: 700;
      color: #60a5fa;
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
    }}
    .subtitle {{
      color: #94a3b8;
      font-size: 13px;
      line-height: 1.5;
      margin-bottom: 20px;
    }}
    .scope-box {{
      background: #1e293b;
      border-radius: 8px;
      padding: 12px;
      font-size: 12px;
      color: #cbd5e1;
      margin-bottom: 20px;
    }}
    .form-group {{
      margin-bottom: 16px;
    }}
    label {{
      display: block;
      font-size: 12px;
      font-weight: 600;
      color: #cbd5e1;
      margin-bottom: 6px;
    }}
    input {{
      width: 100%;
      box-sizing: border-box;
      background: #090d16;
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 10px 12px;
      color: #f8fafc;
      font-size: 14px;
      outline: none;
    }}
    input:focus {{
      border-color: #3b82f6;
    }}
    .btn {{
      width: 100%;
      background: #2563eb;
      color: #ffffff;
      border: none;
      border-radius: 8px;
      padding: 11px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      margin-top: 8px;
    }}
    .btn:hover {{
      background: #1d4ed8;
    }}
  </style>
</head>
<body>
  <div class="auth-card">
    <div class="logo">
      <span>Altero</span>
      <span style="font-size:12px;color:#94a3b8;font-weight:normal;">/ OAuth 2.0</span>
    </div>
    <div class="subtitle">
      应用 <strong>{html.escape(client_id)}</strong> 请求连接您的 Altero 文献库
    </div>
    <div class="scope-box">
      <strong>授予权限：</strong><br>
      • 文献条目与目录访问 (library.read)<br>
      • 标注高亮双向同步 (annotations.write)<br>
      • PDF 附件流式阅读 (files.read)
    </div>
    {error_html}
    <form method="POST" action="/oauth/authorize">
      <input type="hidden" name="client_id" value="{html.escape(client_id)}">
      <input type="hidden" name="redirect_uri" value="{html.escape(redirect_uri)}">
      <input type="hidden" name="scope" value="{html.escape(scope)}">
      <input type="hidden" name="state" value="{html.escape(state)}">
      <input type="hidden" name="code_challenge" value="{html.escape(code_challenge)}">
      <input type="hidden" name="code_challenge_method" value="{html.escape(code_challenge_method)}">
      <input type="hidden" name="nonce" value="{html.escape(nonce or '')}">

      <div class="form-group">
        <label for="username">Altero 用户名或邮箱</label>
        <input type="text" id="username" name="username" required autocomplete="username" autofocus>
      </div>

      <div class="form-group">
        <label for="password">密码</label>
        <input type="password" id="password" name="password" required autocomplete="current-password">
      </div>

      <button type="submit" class="btn">登录并授权 AltCanvas</button>
    </form>
  </div>
</body>
</html>"""
    return HTMLResponse(content=page_html)


@router.get("/oauth/authorize")
async def authorize_get(
    session: SessionDep,
    response_type: str = Query("code"),
    client_id: str = Query("altcanvas"),
    redirect_uri: str = Query(...),
    scope: str = Query("openid profile library.read library.write annotations.read annotations.write files.read"),
    state: str = Query(...),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query("S256"),
    nonce: str | None = Query(None),
) -> Response:
    """Show login/authorization form or auto-grant if already authenticated."""
    await oauth.get_or_create_client(session, client_id, redirect_uri=redirect_uri)
    return render_login_page(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        nonce=nonce,
    )


@router.post("/oauth/authorize")
async def authorize_post(
    session: SessionDep,
    client_id: Annotated[str, Form()],
    redirect_uri: Annotated[str, Form()],
    scope: Annotated[str, Form()],
    state: Annotated[str, Form()],
    code_challenge: Annotated[str, Form()],
    code_challenge_method: Annotated[str, Form()],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    nonce: Annotated[str | None, Form()] = None,
) -> Response:
    """Process login form on authorization page and issue authorization code."""
    identifier = username.strip().lower()
    column = User.email if "@" in identifier else User.username
    user = await session.scalar(select(User).where(func.lower(column) == identifier))

    if not passwords.verify_password(user.password_hash if user else None, password):
        return render_login_page(
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            nonce=nonce,
            error_msg="用户名或密码不正确",
        )

    assert user is not None
    if user.disabled_at is not None:
        return render_login_page(
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            nonce=nonce,
            error_msg="该账户已被禁用",
        )

    code = await oauth.create_authorization_code(
        session=session,
        client_id=client_id,
        user_id=user.id,
        redirect_uri=redirect_uri,
        scopes=scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        nonce=nonce,
    )

    sep = "&" if "?" in redirect_uri else "?"
    callback_url = f"{redirect_uri}{sep}code={code}&state={state}"
    return RedirectResponse(url=callback_url, status_code=302)


@router.post("/oauth/token")
async def token_endpoint(
    session: SessionDep,
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str, Form()] = "altcanvas",
    code: Annotated[str | None, Form()] = None,
    code_verifier: Annotated[str | None, Form()] = None,
    redirect_uri: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Form()] = None,
) -> dict:
    """Exchange authorization code or rotate refresh token."""
    if grant_type == "authorization_code":
        if not code or not code_verifier or not redirect_uri:
            raise InvalidInputError("Missing code, code_verifier, or redirect_uri")
        return await oauth.exchange_code_for_tokens(
            session=session,
            client_id=client_id,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )

    if grant_type == "refresh_token":
        if not refresh_token:
            raise InvalidInputError("Missing refresh_token")
        return await oauth.refresh_tokens(
            session=session,
            client_id=client_id,
            refresh_token_str=refresh_token,
        )

    raise InvalidInputError(f"Unsupported grant_type '{grant_type}'")


@router.post("/oauth/revoke")
async def revoke_endpoint(
    session: SessionDep,
    token: Annotated[str, Form()],
    client_id: Annotated[str, Form()] = "altcanvas",
    token_type_hint: Annotated[str | None, Form()] = None,
) -> dict:
    """Revoke an active access or refresh token."""
    await oauth.revoke_token(session, client_id, token)
    return {"status": "revoked"}


@router.get("/oauth/userinfo")
async def userinfo_endpoint(
    session: SessionDep,
    request: Request,
) -> dict:
    """Return user profile claims for the Bearer access token."""
    credential = get_credential(request)
    if not credential:
        raise ForbiddenError("Missing bearer token")

    token_obj = await oauth.validate_access_token(session, credential)
    if token_obj is None:
        raise ForbiddenError("Invalid access token")

    user = await session.scalar(select(User).where(User.id == token_obj.user_id))
    if user is None:
        raise ForbiddenError("User not found")

    return {
        "sub": str(user.id),
        "id": str(user.id),
        "username": user.username,
        "name": user.display_name or user.username,
        "email": user.email or "",
    }
