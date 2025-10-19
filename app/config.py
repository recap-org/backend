"""
Configuration settings for the application.
"""
from pydantic_settings import BaseSettings
from typing import List, Literal
from pydantic import field_validator
import json


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
    allowed_origins: List[str] = ["http://localhost:4000"]
    
    @field_validator('allowed_origins', mode='before')
    @classmethod
    def parse_allowed_origins(cls, v):
        """Parse allowed_origins from JSON string or list."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # If not valid JSON, treat as single origin
                return [v]
        return v

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
    # Where to redirect after successful OAuth login (default: frontend URL)
    oauth_success_redirect: str | None = None

    # Session Settings
    session_secret_key: str = "change-this-in-production"
    session_cookie_name: str = "recap_session"
    session_https_only: bool = False
    session_same_site: Literal["lax", "strict", "none"] = "lax"  # "none" requires https_only=True
    session_max_age: int = 14 * 24 * 60 * 60  # 14 days in seconds

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
