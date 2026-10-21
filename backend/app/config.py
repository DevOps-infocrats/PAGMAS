from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """All configuration comes from environment variables / backend/.env."""

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field("development", pattern="^(development|production|test)$")
    secret_key: str = Field(..., min_length=32, description="JWT signing key – generate with scripts/generate_env.py")
    # Key rotation: tokens signed with the previous key stay valid until they expire.
    secret_key_previous: str | None = None

    # JWT session tokens
    jwt_algorithm: str = Field("HS256", pattern="^HS(256|384|512)$")
    jwt_issuer: str = Field("pratap-api", min_length=3, max_length=80)
    jwt_audience: str = Field("pratap-dashboard", min_length=3, max_length=80)

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'var' / 'app.db').as_posix()}"
    data_dir: Path = PROJECT_DIR / "data"

    # HTTP / browser security
    cors_origins: list[str] = ["http://localhost:3000"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    # Reverse proxies (the Next.js server) whose X-Forwarded-For header is trusted.
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]
    session_ttl_minutes: int = Field(480, ge=5, le=24 * 60)
    cookie_secure: bool | None = None  # defaults to True in production
    login_max_attempts: int = 5
    login_window_seconds: int = 15 * 60
    account_lockout_threshold: int = 10
    account_lockout_minutes: int = 30
    upload_max_mb: int = Field(60, ge=1, le=500)

    # Business rules (source-defined, see README "Metric definitions")
    healthy_threshold: float = 98.0
    penalty_threshold: float = 90.0  # "Penalty Prone Blocks <90%" in the O&M sheet

    # Administrator login managed from .env (see .env.example). The account is created on start-up
    # when missing; with ADMIN_SYNC_PASSWORD=true its password is reset to the .env value.
    # Prefer ADMIN_PASSWORD_HASH (python scripts/hash_password.py) over a plain ADMIN_PASSWORD.
    admin_email: str | None = Field(None, validation_alias=AliasChoices("ADMIN_EMAIL", "BOOTSTRAP_ADMIN_EMAIL"))
    admin_password: str | None = Field(None, validation_alias=AliasChoices("ADMIN_PASSWORD", "BOOTSTRAP_ADMIN_PASSWORD"))
    admin_password_hash: str | None = Field(None, validation_alias=AliasChoices("ADMIN_PASSWORD_HASH"))
    admin_name: str = Field("Administrator", validation_alias=AliasChoices("ADMIN_NAME"), max_length=120)
    admin_sync_password: bool = Field(False, validation_alias=AliasChoices("ADMIN_SYNC_PASSWORD"))

    @field_validator("secret_key", "secret_key_previous")
    @classmethod
    def _strong_key(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if "change-me" in v.lower():
            raise ValueError("SECRET_KEY is still the placeholder – run scripts/generate_env.py")
        if len(v) < 32 or len(set(v)) < 16:
            raise ValueError("SECRET_KEY has too little entropy – run scripts/generate_env.py")
        return v

    @field_validator("admin_email", "admin_password", "admin_password_hash", mode="before")
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("admin_password_hash")
    @classmethod
    def _argon2_hash(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("$argon2"):
            raise ValueError("ADMIN_PASSWORD_HASH must be an Argon2 hash – create it with scripts/hash_password.py")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "Settings":
        if self.secret_key_previous and self.secret_key_previous == self.secret_key:
            raise ValueError("SECRET_KEY_PREVIOUS must differ from SECRET_KEY")
        if self.admin_password and self.admin_password_hash:
            raise ValueError("Set either ADMIN_PASSWORD or ADMIN_PASSWORD_HASH, not both")
        if self.is_production and self.admin_password:
            raise ValueError("Plain ADMIN_PASSWORD is not allowed in production – use ADMIN_PASSWORD_HASH")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def secure_cookies(self) -> bool:
        return self.is_production if self.cookie_secure is None else self.cookie_secure

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
