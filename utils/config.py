from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # Google Maps
    GOOGLE_MAPS_API_KEY: str = ""

    # Instagram (optional)
    INSTAGRAM_USERNAME: str = ""
    INSTAGRAM_PASSWORD: str = ""

    # Logging
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Scrapy
    SCRAPY_USER_AGENT: str = "smb-intel-co (research project, contact: juanpaperez2603@gmail.com)"

    @field_validator("SUPABASE_URL")
    @classmethod
    def validate_supabase_url(cls, v: str) -> str:
        if not v:
            return v
        if not v.startswith("https://"):
            raise ValueError("SUPABASE_URL must use HTTPS")
        if not v.endswith(".supabase.co"):
            raise ValueError("SUPABASE_URL must end in .supabase.co")
        return v


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    if not Path(".env").exists():
        raise FileNotFoundError("Falta .env — copia .env.template a .env y llena los valores.")
    return Settings()
