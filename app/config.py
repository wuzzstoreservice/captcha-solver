from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Optional, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAPTCHA_SOLVER_",
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 5080
    api_keys: List[str] = Field(default_factory=list)
    browser_type: str = "camoufox"
    thread: int = 1
    headless: bool = True
    proxy_support: bool = True
    task_ttl_seconds: int = 300
    result_ttl_seconds: int = 600
    max_queue: int = 20
    solve_timeout_seconds: int = 120
    debug: bool = False
    proxies_file: str = "proxies.txt"
    # If true, skip Camoufox and use mock solver (tests / CI)
    mock_solver: bool = False

    @field_validator("api_keys", mode="before")
    @classmethod
    def _parse_api_keys(cls, value: Any) -> List[str]:
        if value is None or value == "" or value == []:
            return []
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        return [str(x) for x in parsed if str(x).strip()]
                except json.JSONDecodeError:
                    pass
            return [part.strip() for part in text.split(",") if part.strip()]
        if isinstance(value, list):
            return [str(x) for x in value if str(x).strip()]
        return []

    @property
    def proxies_path(self) -> Path:
        p = Path(self.proxies_file)
        if not p.is_absolute():
            p = ROOT / p
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml_overrides(path: Optional[str] = None) -> None:
    """Optional YAML merge into env-backed settings (call before get_settings cache)."""
    import yaml

    cfg_path = Path(path) if path else ROOT / "config.yaml"
    if not cfg_path.exists():
        return
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    for key, value in data.items():
        env_key = f"CAPTCHA_SOLVER_{key.upper()}"
        if env_key in os.environ or value is None:
            continue
        if isinstance(value, bool):
            os.environ[env_key] = "true" if value else "false"
        elif isinstance(value, list):
            # empty list => leave default; non-empty as comma-separated
            if not value:
                continue
            os.environ[env_key] = ",".join(str(v) for v in value)
        else:
            os.environ[env_key] = str(value)
    get_settings.cache_clear()
