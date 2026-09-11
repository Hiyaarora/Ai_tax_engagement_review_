from app.azure.connectivity import ConnectivityReport, ServiceCheck
from scripts.check_azure import exit_code_for, render_report


def _report() -> ConnectivityReport:
    return ConnectivityReport(
        services=[
            ServiceCheck(
                service="document_intelligence",
                configured=False,
                reachable=False,
                detail="not configured",
            ),
            ServiceCheck(
                service="embeddings", configured=True, reachable=True, detail="ok", latency_ms=812
            ),
            ServiceCheck(
                service="search",
                configured=True,
                reachable=False,
                detail="HttpResponseError: 403",
                latency_ms=95,
            ),
        ]
    )


def test_render_report_one_line_per_service_with_status_marker():
    lines = render_report(_report()).splitlines()
    assert lines[0] == "[SKIP] document_intelligence  not configured"
    assert lines[1] == "[ OK ] embeddings             ok (812 ms)"
    assert lines[2] == "[FAIL] search                 HttpResponseError: 403 (95 ms)"


def test_exit_code_nonzero_when_any_configured_service_unreachable():
    assert exit_code_for(_report()) == 1


def test_exit_code_zero_when_all_configured_services_reachable():
    report = ConnectivityReport(
        services=[
            ServiceCheck(
                service="search", configured=True, reachable=True, detail="ok", latency_ms=1
            )
        ]
    )
    assert exit_code_for(report) == 0
