from pydantic_settings import BaseSettings, SettingsConfigDict
import json
from typing import List, Union

class Settings(BaseSettings):
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment: str = "gpt-5-mini"
    
    # Defaults for CORS in production
    allow_origins: Union[List[str], str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000"]

    # This handles `.env` files.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def get_allow_origins(self) -> List[str]:
        if isinstance(self.allow_origins, str):
            try:
                parsed = json.loads(self.allow_origins)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                return [origin.strip() for origin in self.allow_origins.split(",")]
        return self.allow_origins

settings = Settings()
