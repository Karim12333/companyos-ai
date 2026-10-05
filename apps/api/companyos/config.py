from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    environment: str = "development"
    app_name: str = "CompanyOS"
    web_base_url: str = "http://localhost:3100"
    api_base_url: str = "http://localhost:8000"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3100"])
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://companyos_app:companyos_app_dev@localhost:5442/companyos"
    migration_database_url: str = "postgresql+asyncpg://companyos:companyos_dev@localhost:5442/companyos"
    redis_url: str = "redis://localhost:6379/0"

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "companyos"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "companyos"
    s3_secret_key: SecretStr = SecretStr("companyos_dev_secret")
    s3_bucket: str = "companyos-artifacts"
    s3_region: str = "us-east-1"

    secret_key: SecretStr = SecretStr("dev-insecure-secret-change-me")
    encryption_keys: SecretStr = SecretStr("")
    session_ttl_hours: int = 24 * 14
    session_cookie_name: str = "companyos_session"
    cookie_secure: bool = False

    email_provider: str = "smtp"
    email_from: str = "CompanyOS <notifications@companyos.local>"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    resend_api_key: SecretStr = SecretStr("")

    allow_platform_ai_fallback: bool = False
    platform_ai_base_url: str = "https://api.openai.com/v1"
    platform_ai_api_key: SecretStr = SecretStr("")
    platform_ai_model: str = "gpt-4o-mini"

    tavily_api_key: SecretStr = SecretStr("")
    platform_admin_emails: list[str] = Field(default_factory=list)

    max_upload_bytes: int = 10 * 1024 * 1024
    login_rate_limit_per_minute: int = 10

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
