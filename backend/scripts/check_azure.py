"""Verify the three Azure services are reachable with the current DefaultAzureCredential.

Usage (from backend/):  uv run python -m scripts.check_azure
Exit code 0 = every configured service reachable; 1 = at least one configured service failed.
Run `az login` first. Unconfigured services (empty endpoint in .env) are skipped, not failed.
"""

from __future__ import annotations

import sys

from app.azure.connectivity import ConnectivityReport, run_checks
from app.config import get_settings


def render_report(report: ConnectivityReport) -> str:
    lines = []
    for check in report.services:
        marker = "SKIP" if not check.configured else (" OK " if check.reachable else "FAIL")
        latency = f" ({check.latency_ms} ms)" if check.latency_ms is not None else ""
        lines.append(f"[{marker}] {check.service:<23}{check.detail}{latency}")
    return "\n".join(lines)


def exit_code_for(report: ConnectivityReport) -> int:
    return 0 if report.all_reachable else 1


def main() -> int:
    report = run_checks(get_settings())
    print(render_report(report))
    return exit_code_for(report)


if __name__ == "__main__":
    sys.exit(main())
