from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    bot_token: str
    admin_ids: list[int] = Field(default_factory=list)
    support_username: str = "helpersmmtg"
    # Legal documents (public offer + privacy policy)
    offer_url: str = "https://cutt.ly/8rLOMWWC"
    privacy_url: str = "https://cutt.ly/1rLlQZT0"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "smm_bot"
    postgres_user: str = "smm"
    postgres_password: str = "smm"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    # Panel
    panel_api_url: str = "https://smmpanelus.com/api/v2"
    panel_api_key: str

    # YooKassa
    yookassa_shop_id: str | None = None
    yookassa_secret_key: str | None = None
    yookassa_return_url: str | None = None

    # Crypto Bot (Crypto Pay API) — token from @CryptoBot → Crypto Pay → Create App
    cryptobot_token: str | None = None
    cryptobot_testnet: bool = False
    # Comma-separated assets accepted for fiat invoices, e.g. USDT,TON,BTC
    cryptobot_asset: str = "USDT,TON,BTC"

    # Stars
    stars_enabled: bool = True

    # Referral: % of referred user's order amount credited to referrer balance
    referral_percent: float = 7.0
    # Alert admin when supplier balance falls below this (USD)
    panel_balance_alert_usd: float = 5.0

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    currency: str = "USD"
    default_language: str = "ru"
    services_sync_interval_minutes: int = 60
    order_status_poll_seconds: int = 60
    cache_ttl_seconds: int = 3600

    # Webhook
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080

    # Local mode (no Docker / Postgres / Redis)
    local_mode: bool = False
    sqlite_path: str = "data/bot.db"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [int(v) for v in value]
        if isinstance(value, int):
            return [value]
        return [int(part.strip()) for part in str(value).split(",") if part.strip()]

    @property
    def database_url(self) -> str:
        if self.local_mode:
            return f"sqlite+aiosqlite:///{self.sqlite_path}"
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        if self.local_mode:
            return f"sqlite:///{self.sqlite_path}"
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def celery_broker_url(self) -> str:
        return self.redis_url

    @property
    def celery_result_backend(self) -> str:
        return self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
