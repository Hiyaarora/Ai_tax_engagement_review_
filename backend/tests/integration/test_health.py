def test_health_returns_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "fd-tax-review-backend"
    assert "version" in body


def test_health_reports_azure_config_state(client):
    """Health must say whether Azure is configured without leaking endpoint values."""
    body = client.get("/api/health").json()
    assert "azure" in body
    assert set(body["azure"]) == {"foundry", "search", "document_intelligence"}
    for configured in body["azure"].values():
        assert isinstance(configured, bool)


def test_health_azure_reports_live_connectivity_without_touching_azure(client):
    """The endpoint runs checks through an injectable probe set, so tests never call Azure."""
    from app.api.health import get_probes

    client.app.dependency_overrides[get_probes] = lambda: {
        "document_intelligence": lambda: None,
        "embeddings": lambda: None,
        "search": lambda: None,
    }

    body = client.get("/api/health/azure").json()

    assert [s["service"] for s in body["services"]] == [
        "document_intelligence",
        "embeddings",
        "search",
    ]
    # Nothing is configured in the test environment, so every service is skipped, not probed.
    assert all(s["configured"] is False for s in body["services"])
    assert all(s["detail"] == "not configured" for s in body["services"])
    assert body["all_reachable"] is True
