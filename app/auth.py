"""
Auth routes for GitHub OAuth, split out from main for cleanliness.
"""
from typing import Optional
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from itsdangerous import URLSafeSerializer

from .config import settings


router = APIRouter(prefix="/auth/github", tags=["auth"])


@router.get("/login")
async def github_login(request: Request):
    client_id = getattr(settings, 'github_client_id', None)
    redirect_uri = getattr(settings, 'github_redirect_uri', None)
    if not client_id or not redirect_uri:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured (client_id/redirect_uri)")

    # Create a signed state for CSRF protection
    s = URLSafeSerializer(settings.session_secret_key, salt="github-oauth-state")
    state = s.dumps({"nonce": os.urandom(8).hex()})
    request.session["oauth_state"] = state

    authorize_url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        "&scope=repo%20read:user"
        f"&state={state}"
    )
    return RedirectResponse(authorize_url)


@router.get("/callback")
async def github_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None):
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' parameter")
    # Verify state
    expected = request.session.get("oauth_state")
    if not expected or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")
    s = URLSafeSerializer(settings.session_secret_key, salt="github-oauth-state")
    try:
        s.loads(state)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    client_id = getattr(settings, 'github_client_id', None)
    client_secret = getattr(settings, 'github_client_secret', None)
    redirect_uri = getattr(settings, 'github_redirect_uri', None)
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured")

    token_url = "https://github.com/login/oauth/access_token"
    headers = {
        "Accept": "application/json",
    }
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(token_url, headers=headers, data=payload)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"GitHub token exchange failed: {e}")

    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=502, detail=f"GitHub token exchange error: {detail}")

    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="No access_token returned by GitHub")

    # Store token in session
    request.session["github_token"] = access_token

    # Optionally, fetch user info and store minimal profile
    api_base = getattr(settings, 'github_api_url', 'https://api.github.com').rstrip('/')
    async with httpx.AsyncClient(timeout=30) as client:
        me = await client.get(
            f"{api_base}/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if me.status_code < 400:
        request.session["github_user"] = me.json()

    # Redirect to a simple success page or back to docs
    return RedirectResponse(url="/docs")


@router.get("/me")
async def github_me(request: Request):
    token = request.session.get("github_token")
    if not token:
        return JSONResponse(status_code=401, content={"authenticated": False})
    api_base = getattr(settings, 'github_api_url', 'https://api.github.com').rstrip('/')
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{api_base}/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if resp.status_code >= 400:
        return JSONResponse(status_code=resp.status_code, content={"authenticated": False})
    user = resp.json()
    return {"authenticated": True, "user": user}
