"""Application configuration.

All values come from environment variables (or a local .env file). Only endpoints, deployment names
and IDs live here - never API keys. Azure access uses DefaultAzureCredential (az login locally,
Managed Identity in Azure).
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "fd-tax-review-backend"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "production"] = "development"
    cors_origins: list[str] = ["http://localhost:5173"]
    data_dir: str = "../data"
    database_url: str = "sqlite:///../data/fd_tax_review.db"

    # --- Microsoft Foundry ---
    foundry_project_endpoint: str = ""
    foundry_agent_id: str = ""
    foundry_chat_deployment: str = "gpt-4.1-mini"
    foundry_embedding_deployment: str = "text-embedding-3-small"

    # --- Azure AI Search (Milestone 2) ---
    azure_search_endpoint: str = ""
    azure_search_index_name: str = "fd-evidence"

    # --- Azure AI Document Intelligence (Milestone 2) ---
    azure_document_intelligence_endpoint: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def foundry_configured(self) -> bool:
        return bool(self.foundry_project_endpoint and self.foundry_agent_id)

    @property
    def foundry_resource_endpoint(self) -> str:
        """The AI Services resource that hosts the project's model deployments.

        Model inference (chat, embeddings) is served at ``{resource}/openai/v1``, not under the
        project path, so derive it from the project endpoint rather than adding a second setting.
        """
        return self.foundry_project_endpoint.split("/api/projects/")[0].rstrip("/")

    @property
    def search_configured(self) -> bool:
        return bool(self.azure_search_endpoint)

    @property
    def document_intelligence_configured(self) -> bool:
        return bool(self.azure_document_intelligence_endpoint)


@lru_cache
def get_settings() -> Settings:
    return Settings()
