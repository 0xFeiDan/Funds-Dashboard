from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    redis_url: str = "redis://redis:6379/0"
    app_encryption_key: str
    session_secret: str
    bootstrap_username: str = "admin"
    bootstrap_password: str
    cookie_secure: bool = True
    allowed_origins: str = ""
    reconcile_interval_seconds: int = 45
    stale_warning_seconds: int = 10
    stale_seconds: int = 30
    disconnected_seconds: int = 60
    @property
    def origins(self) -> list[str]: return [x.strip() for x in self.allowed_origins.split(",") if x.strip()]
settings = Settings()
