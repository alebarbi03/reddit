"""Configuration for the Tech.eu funding agent.

Everything is overridable via environment variables (or a .env file next to
this project) using the TECHEU_ prefix, e.g. TECHEU_COMPANIES_PER_POST=4.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Where the data comes from.
    explorer_url: str = "https://funding.tech.eu/"
    # Paths tried in order when looking for the rounds listing. The first one
    # that yields parseable rounds wins.
    explorer_paths: list[str] = ["/rounds", "/", "/deals", "/funding"]
    rss_url: str = "https://tech.eu/feed/"

    # What counts as "this morning's" news.
    lookback_days: int = 3
    min_amount_eur: float = 0.0
    only_new: bool = True  # skip rounds already reported on a previous run

    # Post shape.
    companies_per_post: int = 5
    max_posts: int = 3
    include_partial_post: bool = True  # emit a final post with <5 companies
    max_post_chars: int = 2900  # LinkedIn's hard limit is 3000

    # Browser behaviour.
    headless: bool = True
    page_timeout_ms: int = 45_000
    settle_ms: int = 4_000
    scroll_passes: int = 6

    # Local storage.
    db_path: str = str(BASE_DIR / "data" / "funding.db")
    output_dir: str = str(BASE_DIR / "out")

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        env_prefix="techeu_",
        extra="ignore",
    )

    @property
    def resolved_db_path(self) -> Path:
        p = Path(self.db_path)
        return p if p.is_absolute() else (BASE_DIR / p).resolve()

    @property
    def resolved_output_dir(self) -> Path:
        p = Path(self.output_dir)
        return p if p.is_absolute() else (BASE_DIR / p).resolve()

    def explorer_candidates(self) -> list[str]:
        """Absolute URLs to try, de-duplicated and in preference order."""
        base = self.explorer_url.rstrip("/")
        urls: list[str] = []
        for path in self.explorer_paths:
            url = base + "/" + path.lstrip("/") if path != "/" else base + "/"
            if url not in urls:
                urls.append(url)
        return urls


settings = Settings()
