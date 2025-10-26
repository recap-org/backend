"""
FastAPI backend for dynamically generating and serving cookiecutter templates.
"""
from .auth import router as auth_router
from .cookiecutter import router as cookiecutter_router
from pathlib import Path
from typing import List

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import httpx

try:
    from .config import settings
except ImportError:
    # Fallback for running directly
    import os

    class Settings:
        app_name = 'Recap Template API'
        app_version = '1.0.0'
        allowed_origins = ['*']
        cookiecutter_base_path = 'cookiecutter'
        github_api_url = 'https://api.github.com'
        github_default_org = None
        github_client_id = os.environ.get('GITHUB_CLIENT_ID')
        github_client_secret = os.environ.get('GITHUB_CLIENT_SECRET')
        github_redirect_uri = os.environ.get('GITHUB_REDIRECT_URI')
        session_secret_key = os.environ.get(
            'SESSION_SECRET_KEY', 'change-this-in-production')
        session_cookie_name = os.environ.get(
            'SESSION_COOKIE_NAME', 'recap_session')
        session_https_only = os.environ.get(
            'SESSION_HTTPS_ONLY', 'False') == 'True'
        session_same_site = os.environ.get('SESSION_SAME_SITE', 'lax')
        session_max_age = int(os.environ.get(
            'SESSION_MAX_AGE', str(14 * 24 * 60 * 60)))
    settings = Settings()


# Initialize FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="API for generating cookiecutter templates dynamically",
    version=settings.app_version
)

# Configure CORS to allow the Jekyll frontend to access the API
app.add_middleware(
    CORSMiddleware,
    # In production, replace with specific domain
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sessions for OAuth
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    session_cookie=settings.session_cookie_name,
    https_only=settings.session_https_only,
    same_site=settings.session_same_site,  # type: ignore
    max_age=settings.session_max_age,
)

# Path to cookiecutter templates
COOKIECUTTER_BASE = Path(__file__).parent.parent / \
    settings.cookiecutter_base_path


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": settings.app_name,
        "version": settings.app_version,
        "status": "operational",
        "endpoints": {
            "/cookiecutter": "List available templates",
            "/cookiecutter/{template_name}": "Get template configuration",
            "/cookiecutter/{template_name}/download": "Generate a template and download it",
            "/cookiecutter/{template_name}/github": "Generate a template and create a GitHub repository for the authenticated user or org",
            "/auth/github/login": "Start GitHub OAuth login flow",
            "/auth/github/callback": "OAuth callback endpoint",
            "/auth/github/me": "Get the authenticated GitHub user (if logged in)"
        }
    }

# --- GitHub OAuth: Login and Callback ---
app.include_router(auth_router)
app.include_router(cookiecutter_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
