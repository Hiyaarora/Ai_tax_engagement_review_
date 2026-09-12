import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.config import Settings
from app.observability.tracing import (
    TRACER_NAME,
    TracingMode,
    resolve_tracing_mode,
    span,
    use_in_memory_tracing,
)


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    use_in_memory_tracing(exporter)
    yield exporter
    exporter.clear()


def test_span_records_name_attributes_and_nesting(exporter: InMemorySpanExporter):
    with span("review.run", engagement_id="acme-2025", review_id="rev_1") as outer:
        outer.set_attribute("flags", 3)
        with span("tool.analyze_sales_by_state", engagement_id="acme-2025"):
            pass

    finished = {s.name: s for s in exporter.get_finished_spans()}
    assert set(finished) == {"review.run", "tool.analyze_sales_by_state"}
    assert finished["review.run"].attributes["engagement_id"] == "acme-2025"
    assert finished["review.run"].attributes["flags"] == 3
    assert (
        finished["tool.analyze_sales_by_state"].parent.span_id
        == finished["review.run"].context.span_id
    )
    assert finished["review.run"].instrumentation_scope.name == TRACER_NAME


def test_span_records_exception_and_error_status(exporter: InMemorySpanExporter):
    with pytest.raises(RuntimeError):
        with span("embed", count=2):
            raise RuntimeError("boom")
    [s] = exporter.get_finished_spans()
    assert s.status.status_code == trace.StatusCode.ERROR
    assert any(e.name == "exception" for e in s.events)


def test_span_drops_none_attributes(exporter: InMemorySpanExporter):
    with span("search.hybrid", top_score=None, hits=2):
        pass
    [s] = exporter.get_finished_spans()
    assert "top_score" not in s.attributes and s.attributes["hits"] == 2


def test_tracing_mode_resolution():
    assert resolve_tracing_mode(Settings(_env_file=None)) == TracingMode.LOCAL
    assert (
        resolve_tracing_mode(
            Settings(_env_file=None, applicationinsights_connection_string="InstrumentationKey=x")
        )
        == TracingMode.AZURE_MONITOR
    )
    assert (
        resolve_tracing_mode(Settings(_env_file=None, otel_console_export=True))
        == TracingMode.CONSOLE
    )


def test_use_in_memory_tracing_installs_a_provider_that_exports_to_the_given_exporter():
    exporter = InMemorySpanExporter()
    use_in_memory_tracing(exporter)
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    with span("x"):
        pass
    assert [s.name for s in exporter.get_finished_spans()] == ["x"]
    # A second call must not raise or stack processors.
    exporter2 = InMemorySpanExporter()
    use_in_memory_tracing(exporter2)
    with span("y"):
        pass
    assert [s.name for s in exporter2.get_finished_spans()] == ["y"]
    assert all(s.name != "y" for s in exporter.get_finished_spans())


def test_configure_tracing_is_idempotent_for_local_mode():
    from app.observability import tracing

    tracing.reset_for_tests()
    settings = Settings(_env_file=None)
    first = tracing.configure_tracing(settings)
    provider_after_first = tracing._provider
    second = tracing.configure_tracing(settings)
    assert first == second == TracingMode.LOCAL
    assert tracing._provider is provider_after_first  # not rebuilt on every create_app()


def test_foundry_lookup_is_used_only_when_enabled(monkeypatch):
    from app.observability import tracing

    calls: list[str] = []

    def fake_lookup(settings: Settings) -> str:
        calls.append(settings.foundry_project_endpoint)
        return "InstrumentationKey=from-foundry"

    monkeypatch.setattr(tracing, "_lookup_foundry_connection_string", fake_lookup)
    base = dict(
        _env_file=None, foundry_project_endpoint="https://x.services.ai.azure.com/api/projects/p"
    )

    assert tracing.resolve_connection_string(Settings(**base)) == ""
    assert calls == []
    assert (
        tracing.resolve_connection_string(Settings(**base, otel_use_foundry_app_insights=True))
        == "InstrumentationKey=from-foundry"
    )
    assert calls == ["https://x.services.ai.azure.com/api/projects/p"]
    # explicit setting wins without a lookup
    assert (
        tracing.resolve_connection_string(
            Settings(
                **base,
                otel_use_foundry_app_insights=True,
                applicationinsights_connection_string="InstrumentationKey=explicit",
            )
        )
        == "InstrumentationKey=explicit"
    )
    assert len(calls) == 1


def test_foundry_lookup_failure_falls_back_to_local(monkeypatch):
    from app.observability import tracing

    def boom(settings: Settings) -> str:
        raise RuntimeError("No Application Insights connection found.")

    monkeypatch.setattr(tracing, "_lookup_foundry_connection_string", boom)
    settings = Settings(
        _env_file=None,
        foundry_project_endpoint="https://x.services.ai.azure.com/api/projects/p",
        otel_use_foundry_app_insights=True,
    )
    assert tracing.resolve_connection_string(settings) == ""
    assert tracing.resolve_tracing_mode(settings) == TracingMode.LOCAL


def test_genai_instrumentation_is_enabled_when_exporting(monkeypatch):
    from app.observability import tracing

    monkeypatch.delenv("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", raising=False)
    calls: list[dict] = []

    class _FakeInstrumentor:
        def is_instrumented(self) -> bool:
            return bool(calls)

        def instrument(self, **kwargs) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(tracing, "_genai_instrumentor", lambda: _FakeInstrumentor())
    tracing.reset_for_tests()

    mode = tracing.configure_tracing(Settings(_env_file=None, otel_console_export=True))

    assert mode == TracingMode.CONSOLE
    assert calls == [{"enable_content_recording": False}]
    assert __import__("os").environ["AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING"] == "true"
    from azure.core.settings import settings as azure_settings

    assert azure_settings.tracing_implementation() is not None  # azure-core -> OTel bridge on
    tracing.reset_for_tests()


def test_genai_instrumentation_is_skipped_in_local_mode(monkeypatch):
    from app.observability import tracing

    monkeypatch.setattr(
        tracing,
        "_genai_instrumentor",
        lambda: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    tracing.reset_for_tests()
    assert tracing.configure_tracing(Settings(_env_file=None)) == TracingMode.LOCAL
    tracing.reset_for_tests()
