from pathlib import Path
import os
from dataclasses import dataclass, field


BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_path = BASE_DIR / ".env"
if env_path.exists():
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'taskapp.db'}")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


@dataclass
class Settings:
    PROJECT_NAME: str = "TaskApp API"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = field(
        default_factory=lambda: os.environ.get("SECRET_KEY", "super-secret-dev-key-change-in-prod")
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    DATABASE_URL: str = field(default_factory=_get_database_url)
    GOOGLE_CLIENT_ID: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_ID", ""))
    GOOGLE_CLIENT_SECRET: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_SECRET", ""))
    FRONTEND_URL: str = field(
        default_factory=lambda: os.environ.get("FRONTEND_URL", "http://localhost:5173")
    )
    BACKEND_URL: str = field(
        default_factory=lambda: os.environ.get("BACKEND_URL", "http://localhost:8000")
    )


settings = Settings()
