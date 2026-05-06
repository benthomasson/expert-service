"""Authentication: Google OAuth + bearer token with dev-mode bypass."""

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from expert_service.config import settings
from expert_service.db.connection import get_session
from expert_service.db.models import User
from expert_service.rbac import UserInfo, Role

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)


# --- OAuth routes ---


@router.get("/login")
async def login(request: Request):
    from expert_service.app import oauth

    if not oauth:
        return HTMLResponse("OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.", status_code=501)
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, str(redirect_uri))


@router.get("/auth/callback")
async def auth_callback(request: Request, session: AsyncSession = Depends(get_session)):
    from expert_service.app import oauth

    if not oauth:
        return HTMLResponse("OAuth not configured", status_code=501)

    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo", {})
    email = userinfo.get("email", "")

    if not email:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;display:flex;justify-content:center;"
            "align-items:center;height:100vh;'><div style='text-align:center'>"
            "<h1>Access Denied</h1><p>Could not retrieve email from Google.</p>"
            "</div></body></html>",
            status_code=403,
        )

    email = email.strip().lower()
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;display:flex;justify-content:center;"
            "align-items:center;height:100vh;'><div style='text-align:center'>"
            "<h1>Access Denied</h1><p>Your account is not authorized for Expert Service.</p>"
            "</div></body></html>",
            status_code=403,
        )

    # Clear existing session to prevent session fixation
    request.session.clear()
    request.session["user_email"] = email
    request.session["user_name"] = userinfo.get("name", email)
    return RedirectResponse(url="/")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    response = RedirectResponse(url="/login")
    response.delete_cookie("session")
    return response


# --- Dual auth dependency ---


async def verify_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> UserInfo:
    """Authenticate via bearer token, OAuth session, or dev-mode bypass."""

    # 1. Bearer token (API/programmatic access)
    if credentials and settings.api_key and hmac.compare_digest(credentials.credentials, settings.api_key):
        user = UserInfo(identity="api", role=Role.ADMIN)
        request.state.user = user
        return user

    # 2. OAuth session (browser access)
    email = request.session.get("user_email")
    if email:
        result = await session.execute(select(User).where(User.email == email))
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise HTTPException(status_code=403, detail="User not registered")
        user = UserInfo(
            identity=email,
            role=db_user.role,
            display_name=db_user.display_name,
        )
        request.state.user = user
        return user

    # 3. Dev mode — no OAuth configured, allow anonymous access
    if not settings.google_client_id:
        user = UserInfo(identity="dev", role=Role.ADMIN, display_name="Developer")
        request.state.user = user
        return user

    raise HTTPException(status_code=401, detail="Not authenticated")


class _LoginRedirect(Exception):
    """Raised to trigger a redirect to /login for unauthenticated web requests."""
    pass


async def verify_auth_web(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_session),
) -> UserInfo:
    """Same as verify_auth but redirects to /login for unauthenticated browser requests."""
    try:
        return await verify_auth(request, credentials, session)
    except HTTPException as e:
        if e.status_code == 401:
            raise _LoginRedirect()
        raise
