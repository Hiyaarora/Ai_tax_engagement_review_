from app.azure.connectivity import ConnectivityReport, ServiceCheck, check_service, run_checks
from app.config import Settings


def test_unconfigured_service_is_skipped_without_calling_probe():
    called = False

    def probe() -> None:
        nonlocal called
        called = True

    check = check_service("search", configured=False, probe=probe)

    assert check == ServiceCheck(
        service="search", configured=False, reachable=False, detail="not configured"
    )
    assert called is False


def test_reachable_service_reports_latency():
    check = check_service("search", configured=True, probe=lambda: None)
    assert check.reachable is True
    assert check.detail == "ok"
    assert check.latency_ms is not None and check.latency_ms >= 0


def test_failing_probe_reports_error_type_and_message():
    def probe() -> None:
        raise PermissionError("403 Forbidden: caller lacks role")

    check = check_service("search", configured=True, probe=probe)
    assert check.reachable is False
    assert check.detail == "PermissionError: 403 Forbidden: caller lacks role"


def test_run_checks_covers_all_three_services_and_overall_flag():
    settings = Settings(
        _env_file=None,
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        azure_search_endpoint="https://example.search.windows.net",
        azure_document_intelligence_endpoint="",
    )
    probes = {
        "document_intelligence": lambda: None,
        "embeddings": lambda: None,
        "search": lambda: (_ for _ in ()).throw(TimeoutError("timed out")),
    }

    report = run_checks(settings, probes=probes)

    assert isinstance(report, ConnectivityReport)
    assert [c.service for c in report.services] == ["document_intelligence", "embeddings", "search"]
    by_name = {c.service: c for c in report.services}
    assert by_name["document_intelligence"].configured is False
    assert by_name["embeddings"].reachable is True
    assert by_name["search"].reachable is False
    assert report.all_reachable is False


def test_run_checks_all_reachable_when_every_configured_probe_succeeds():
    settings = Settings(
        _env_file=None,
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        azure_search_endpoint="https://example.search.windows.net",
        azure_document_intelligence_endpoint="https://example.cognitiveservices.azure.com/",
    )
    probes = {name: (lambda: None) for name in ("document_intelligence", "embeddings", "search")}
    assert run_checks(settings, probes=probes).all_reachable is True
