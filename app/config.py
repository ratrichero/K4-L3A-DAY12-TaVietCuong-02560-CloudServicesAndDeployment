"""12-Factor settings. Mock mode never requires database/provider credentials."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore",
        env_ignore_empty=True, hide_input_in_errors=True,
    )

    port: int = Field(default=8000, ge=1, le=65535)
    agent_api_key: str = Field(min_length=1, repr=False)  # required: fail fast
    redis_url: str = Field(default="redis://localhost:6379/0", repr=False)
    rate_limit_per_minute: int = Field(default=10, ge=1)
    monthly_budget_usd: float = Field(default=10.0, ge=0, allow_inf_nan=False)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    real_agent_enabled: bool = False
    real_agent_global_budget_usd: float = Field(default=10.0, ge=0, allow_inf_nan=False)
    database_url: str = Field(default="", repr=False)
    llm_primary_base_url: str = ""
    llm_primary_api_key: str = Field(default="", repr=False)
    llm_primary_model: str = ""
    llm_secondary_base_url: str = ""
    llm_secondary_api_key: str = Field(default="", repr=False)
    llm_secondary_model: str = ""
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=60, allow_inf_nan=False)
    llm_output_limit_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    llm_max_output_tokens: int = Field(default=1200, ge=1, le=4096)
    llm_max_input_tokens: int = Field(default=32000, ge=1000, le=100000)
    # No guessed pricing: real mode requires explicit ceilings across both providers.
    llm_max_input_usd_per_million: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    llm_max_output_usd_per_million: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_real_mode(self):
        if not self.real_agent_enabled:
            return self
        if not self.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("Real mode requires a PostgreSQL DATABASE_URL (libpq URI).")
        if self.llm_max_input_usd_per_million is None or self.llm_max_output_usd_per_million is None:
            raise ValueError("Real mode requires both LLM_MAX_*_USD_PER_MILLION price ceilings.")
        for prefix in ("llm_primary", "llm_secondary"):
            base, key, model = (getattr(self, f"{prefix}_{part}").strip()
                                for part in ("base_url", "api_key", "model"))
            if prefix == "llm_secondary" and not any((base, key, model)):
                continue
            if not all((base, key, model)):
                raise ValueError(f"Configure all three {prefix.upper()} provider fields.")
            url = urlsplit(base)
            if (url.scheme != "https" or not url.hostname or url.username or url.password
                    or url.query or url.fragment or url.path.rstrip("/").endswith("/chat/completions")):
                raise ValueError(f"{prefix.upper()}_BASE_URL must be an HTTPS base URL, without credentials/query/completion path.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
