from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings

router = APIRouter(tags=["health"])


class AzureConfigState(BaseModel):
    foundry: bool
    search: bool
    document_intelligence: bool


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    azure: AzureConfigState


@router.get("/health", response_model=HealthResponse)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Liveness check. Reports which Azure services are configured (booleans only, no endpoints)."""
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        azure=AzureConfigState(
            foundry=settings.foundry_configured,
            search=settings.search_configured,
            document_intelligence=settings.document_intelligence_configured,
        ),
    )
