from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Oricred"
    debug: bool = True

    tsa_api_key: str = ""
    tsa_base_url: str = "https://api.tenders-sa.org"

    database_url: str = f"sqlite+aiosqlite:///{Path(__file__).resolve().parent.parent / 'oricred.db'}"
    redis_url: str = ""

    jwt_secret: str = "oricred-dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "noreply@oricred.com"
    email_from_name: str = "Oricred Platform"

    monday_api_key: str = ""

    session_secret: str = "oricred-dev-secret-change-in-production"

    model_config = {"env_prefix": "ORICRED_", "env_file": "../.env"}

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+aiosqlite", "")


settings = Settings()
