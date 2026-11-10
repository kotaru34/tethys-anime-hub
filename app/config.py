from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    database_url: str = 'sqlite+pysqlite:///./test_catalog.db'
    app_username: str = 'admin'
    app_password: str = ''
    session_secret: str = ''
    jellyfin_url: str = ''
    jellyfin_public_url: str = ''
    jellyfin_api_key: str = ''
    state_dir: str = '/state'
    anime_path: str = '/Anime'
    sync_interval_seconds: int = 1800
    enrich_interval_seconds: int = 7200
    subtitle_interval_seconds: int = 10800
    llm_base_url: str = ''
    llm_model: str = ''
    llm_api_key: str = ''

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)


@lru_cache
def settings() -> Settings:
    return Settings()
