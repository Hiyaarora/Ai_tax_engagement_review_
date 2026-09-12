"""Log records carry the active trace/span ids so a log line can be found from a trace and back."""

from __future__ import annotations

import logging

from opentelemetry import trace

_FORMAT = "%(asctime)s %(levelname)s %(name)s trace=%(trace_id)s span=%(span_id)s %(message)s"


class TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = trace.get_current_span().get_span_context()
        record.trace_id = f"{context.trace_id:032x}" if context.is_valid else "-"
        record.span_id = f"{context.span_id:016x}" if context.is_valid else "-"
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Root logging with trace correlation. Idempotent."""
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format=_FORMAT)
    for handler in root.handlers:
        if not any(isinstance(f, TraceContextFilter) for f in handler.filters):
            handler.addFilter(TraceContextFilter())
            handler.setFormatter(logging.Formatter(_FORMAT))
