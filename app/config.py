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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
