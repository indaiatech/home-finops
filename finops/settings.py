"""Application settings loaded from environment variables and `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://finops:change_me_local_dev_password@localhost:5432/finops"
    finops_config_dir: Path = ROOT_DIR / "local"
    finops_api_port: int = 8080
    finops_web_port: int = 5173
    finops_mcp_port: int = 8090
    finops_api_base_url: str = "http://localhost:8080"
    finops_mcp_token: str = ""
    finops_sync_interval_minutes: int = 360
    pluggy_api_base_url: str = "https://api.pluggy.ai"

    def resolved_config_dir(self) -> Path:
        if self.finops_config_dir.is_absolute():
            return self.finops_config_dir
        return (ROOT_DIR / self.finops_config_dir).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
