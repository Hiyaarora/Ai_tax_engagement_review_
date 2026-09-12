import logging

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability.logging import TraceContextFilter, configure_logging
from app.observability.tracing import span, use_in_memory_tracing


def test_filter_adds_trace_and_span_ids_inside_a_span_and_dashes_outside():
    use_in_memory_tracing(InMemorySpanExporter())
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    assert TraceContextFilter().filter(record) is True
    assert record.trace_id == "-" and record.span_id == "-"  # type: ignore[attr-defined]

    with span("review.run"):
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
        TraceContextFilter().filter(record)
        assert len(record.trace_id) == 32 and len(record.span_id) == 16  # type: ignore[attr-defined]


def test_configure_logging_installs_filter_once(caplog):
    configure_logging()
    configure_logging()
    root = logging.getLogger()
    assert sum(isinstance(f, TraceContextFilter) for h in root.handlers for f in h.filters) <= len(
        root.handlers
    )
    with caplog.at_level(logging.INFO, logger="app.test"):
        logging.getLogger("app.test").info("hello")
    assert caplog.records[-1].trace_id == "-"  # type: ignore[attr-defined]
