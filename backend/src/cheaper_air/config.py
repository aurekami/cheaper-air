from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://cheaper_air:cheaper_air@localhost:5432/cheaper_air"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:14b"
    serpapi_api_key: SecretStr | None = None
