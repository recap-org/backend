"""
Configuration settings for the application.
"""
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application settings."""

    # API Settings
    app_name: str = "Recap Template API"
    app_version: str = "1.0.0"

    # Server Settings
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS Settings
    # In production, set to specific domains
    allowed_origins: List[str] = ["*"]

    # Template Settings
    # Now that cookiecutter/ is at repo root, default to that
    cookiecutter_base_path: str = "./cookiecutter"

    # GitHub Settings
    # You can provide a token via env var GITHUB_TOKEN or use Authorization header per-request
    github_api_url: str = "https://api.github.com"
    github_default_org: str | None = None

    # OAuth App Settings
    github_client_id: str | None = None
    github_client_secret: str | None = None
    # e.g., http://localhost:8000/auth/github/callback (must match GitHub app config)
    github_redirect_uri: str | None = None

    # Session Settings
    session_secret_key: str = "change-this-in-production"
    session_cookie_name: str = "recap_session"
    session_https_only: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
