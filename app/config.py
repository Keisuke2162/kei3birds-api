from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from supabase import create_client, Client


class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    cloudflare_r2_access_key: str
    cloudflare_r2_secret_key: str
    cloudflare_r2_bucket: str = "kei3birds-images"
    cloudflare_r2_endpoint: str
    anthropic_api_key: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_supabase() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_key)
