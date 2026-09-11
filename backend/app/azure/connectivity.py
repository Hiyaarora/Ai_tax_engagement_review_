"""Connectivity checks: can this process reach each Azure service with its current credential?

Used by ``GET /api/health/azure`` and ``scripts/check_azure.py``. Each probe is one cheap
authenticated call; failures are reported, never raised, so one broken service can't hide another.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from pydantic import BaseModel

from app.config import Settings

Probe = Callable[[], None]

SERVICE_NAMES = ("document_intelligence", "embeddings", "search")


class ServiceCheck(BaseModel):
    service: str
    configured: bool
    reachable: bool
    detail: str
    latency_ms: int | None = None


class ConnectivityReport(BaseModel):
    services: list[ServiceCheck]

    @property
    def all_reachable(self) -> bool:
        return all(check.reachable for check in self.services if check.configured)


def check_service(name: str, *, configured: bool, probe: Probe) -> ServiceCheck:
    if not configured:
        return ServiceCheck(
            service=name, configured=False, reachable=False, detail="not configured"
        )
    started = time.perf_counter()
    try:
        probe()
    except Exception as exc:  # noqa: BLE001 - we want to report any failure, not crash
        return ServiceCheck(
            service=name,
            configured=True,
            reachable=False,
            detail=f"{type(exc).__name__}: {exc}",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    return ServiceCheck(
        service=name,
        configured=True,
        reachable=True,
        detail="ok",
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _configured_flags(settings: Settings) -> dict[str, bool]:
    return {
        "document_intelligence": settings.document_intelligence_configured,
        "embeddings": bool(settings.foundry_project_endpoint),
        "search": settings.search_configured,
    }


def default_probes(settings: Settings) -> dict[str, Probe]:
    """Real probes. Clients are built lazily per probe, so an unconfigured service costs nothing."""
    from app.azure.document_intelligence import DocumentIntelligenceService
    from app.azure.embeddings import EmbeddingService
    from app.azure.search import SearchService

    return {
        "document_intelligence": lambda: DocumentIntelligenceService.from_settings(settings).ping(),
        "embeddings": lambda: EmbeddingService.from_settings(settings).ping(),
        "search": lambda: SearchService.from_settings(settings).ping(),
    }


def run_checks(settings: Settings, *, probes: dict[str, Probe] | None = None) -> ConnectivityReport:
    probes = probes if probes is not None else default_probes(settings)
    configured = _configured_flags(settings)
    return ConnectivityReport(
        services=[
            check_service(name, configured=configured[name], probe=probes[name])
            for name in SERVICE_NAMES
        ]
    )
