"""FastAPI application factory for the F&D Tax Engagement Review Agent.

Decision support only - not tax advice. All demo data is synthetic.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import engagements, health, reviews
from app.config import get_settings
from app.observability.logging import configure_logging
from app.observability.tracing import configure_tracing

API_PREFIX = "/api"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    configure_tracing(settings)

    app = FastAPI(
        title="F&D Tax Engagement Review Agent",
        version=settings.app_version,
        description=(
            "Reviews synthetic tax engagement documents and produces potential risk flags "
            "with cited evidence. Decision support only - not tax advice."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(engagements.router, prefix=API_PREFIX)
    app.include_router(reviews.router, prefix=API_PREFIX)
    return app


app = create_app()
