from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "subfit:draft-checker:v1.0"

    subfit_db_path: str = str(BASE_DIR / "data" / "subfit.db")
    subfit_default_post_limit: int = 3000
    subfit_max_post_limit: int = 5000

    embedding_model_name: str = "all-MiniLM-L6-v2"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def has_reddit_credentials(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_client_secret)

    @property
    def resolved_db_path(self) -> str:
        """Resolves subfit_db_path against the project root if it's relative,
        so the database location doesn't depend on the process's cwd (e.g.
        running uvicorn from repo root vs. from backend/)."""
        p = Path(self.subfit_db_path)
        return str(p if p.is_absolute() else (BASE_DIR / p).resolve())


settings = Settings()
