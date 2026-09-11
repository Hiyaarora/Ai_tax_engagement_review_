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
