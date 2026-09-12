"""OpenTelemetry tracing for the review pipeline.

Modes (chosen from settings at startup, see ``configure_tracing``):
* ``AZURE_MONITOR`` - export to Application Insights so runs appear in the Foundry **Tracing** tab.
  Uses ``APPLICATIONINSIGHTS_CONNECTION_STRING`` or, when empty, the connection string of the
  Application Insights resource attached to the Foundry project.
* ``CONSOLE`` - print spans to stdout (``OTEL_CONSOLE_EXPORT=true``), handy for local work.
* ``LOCAL`` - spans are created but not exported; zero cost, nothing to configure.

Span names are stable and documented in the README; attributes carry ids and counts only, never
document text, answers or secrets.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor, SpanExporter

from app.config import Settings

log = logging.getLogger(__name__)

TRACER_NAME = "fd-tax-review"
SERVICE_NAME = "fd-tax-review-backend"


class TracingMode(StrEnum):
    LOCAL = "local"
    CONSOLE = "console"
    AZURE_MONITOR = "azure_monitor"


_provider: TracerProvider | None = None
_tracer: trace.Tracer = trace.get_tracer(TRACER_NAME)  # no-op until configured
_global_set = False
_configured_mode: TracingMode | None = None


def _install(provider: TracerProvider) -> None:
    """Make ``provider`` the one this module traces with (and the global one, first time only)."""
    global _provider, _tracer, _global_set
    if _provider is not None:
        _provider.shutdown()
    _provider = provider
    _tracer = provider.get_tracer(TRACER_NAME)
    if not _global_set:
        trace.set_tracer_provider(provider)
        _global_set = True


def _resource() -> Resource:
    return Resource.create({"service.name": SERVICE_NAME})


def _lookup_foundry_connection_string(settings: Settings) -> str:
    """Connection string of the Application Insights resource attached to the Foundry project."""
    from azure.ai.projects import AIProjectClient

    from app.azure.credential import get_credential

    client = AIProjectClient(settings.foundry_project_endpoint, get_credential())
    return str(client.telemetry.get_application_insights_connection_string())


def resolve_connection_string(settings: Settings) -> str:
    """Explicit setting first; else (opt-in) the project's Application Insights; else empty."""
    if settings.applicationinsights_connection_string:
        return settings.applicationinsights_connection_string
    if settings.otel_use_foundry_app_insights and settings.foundry_project_endpoint:
        try:
            return _lookup_foundry_connection_string(settings)
        except Exception as exc:  # noqa: BLE001 - tracing must never block startup
            log.warning("tracing: no Application Insights via Foundry project (%s)", exc)
    return ""


def _genai_instrumentor() -> Any:
    from azure.ai.projects.telemetry import AIProjectInstrumentor

    return AIProjectInstrumentor()


def _enable_genai_spans() -> None:
    """Emit standard ``gen_ai.*`` spans for every OpenAI Responses call (agent runs and questions).

    These are what the Foundry **Tracing** tab lists; our own spans become their parents. Content
    recording stays off so prompts and answers are never stored in telemetry.
    """
    os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")
    try:
        # Azure SDK spans are no-ops until the azure-core -> OpenTelemetry bridge is selected.
        from azure.core.settings import settings as azure_settings

        azure_settings.tracing_implementation = "opentelemetry"
        instrumentor = _genai_instrumentor()
        if not instrumentor.is_instrumented():
            instrumentor.instrument(enable_content_recording=False)
    except Exception as exc:  # noqa: BLE001 - optional enrichment, never fatal
        log.warning("tracing: GenAI instrumentation unavailable (%s)", exc)


def reset_for_tests() -> None:
    """Forget the configured mode and drop any exporter so nothing outlives a test."""
    global _configured_mode
    _configured_mode = None
    _install(TracerProvider(resource=_resource()))


def resolve_tracing_mode(settings: Settings) -> TracingMode:
    if resolve_connection_string(settings):
        return TracingMode.AZURE_MONITOR
    if settings.otel_console_export:
        return TracingMode.CONSOLE
    return TracingMode.LOCAL


def configure_tracing(settings: Settings) -> TracingMode:
    """Set up tracing for the process. Idempotent; called from the app factory."""
    global _configured_mode
    if _configured_mode is not None:
        return _configured_mode
    connection_string = resolve_connection_string(settings)
    mode = (
        TracingMode.AZURE_MONITOR
        if connection_string
        else TracingMode.CONSOLE
        if settings.otel_console_export
        else TracingMode.LOCAL
    )
    _configured_mode = mode
    if mode is not TracingMode.LOCAL:
        _enable_genai_spans()
    if mode is TracingMode.AZURE_MONITOR:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=connection_string,
            resource=_resource(),
            enable_live_metrics=False,
        )
        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            global _provider, _tracer, _global_set
            _provider, _tracer, _global_set = provider, provider.get_tracer(TRACER_NAME), True
        log.info("tracing: exporting to Application Insights")
        return mode
    provider = TracerProvider(resource=_resource())
    if mode is TracingMode.CONSOLE:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        log.info("tracing: console export")
    else:
        log.info("tracing: local only (no exporter configured)")
    _install(provider)
    return mode


def use_in_memory_tracing(exporter: SpanExporter) -> None:
    """Test hook: route every span produced by this module to ``exporter``."""
    provider = TracerProvider(resource=_resource())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    _install(provider)


def _clean(attributes: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in attributes.items() if value is not None}


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """Open a span; ``None`` attributes are dropped. Exceptions are recorded and re-raised."""
    with _tracer.start_as_current_span(name, attributes=_clean(attributes)) as current:
        yield current


def current_trace_id() -> str | None:
    """Hex trace id of the active span, for log correlation; None when not tracing."""
    context = trace.get_current_span().get_span_context()
    return f"{context.trace_id:032x}" if context.is_valid else None
