from app.azure.search import SearchService
from app.config import Settings


class _FakeIndexClient:
    def __init__(self, names: list[str]) -> None:
        self._names = names
        self.stats_calls = 0

    def list_index_names(self):
        yield from self._names

    def get_service_statistics(self):
        self.stats_calls += 1
        return {"counters": {"documentCount": {"usage": 0}}}


def _service(client: _FakeIndexClient) -> SearchService:
    return SearchService(index_client=client, index_name="fd-evidence")  # type: ignore[arg-type]


def test_index_exists_true_when_index_listed():
    assert _service(_FakeIndexClient(["fd-evidence"])).index_exists() is True


def test_index_exists_false_when_index_missing():
    assert _service(_FakeIndexClient(["other"])).index_exists() is False


def test_ping_calls_service_statistics():
    client = _FakeIndexClient([])
    _service(client).ping()
    assert client.stats_calls == 1


def test_from_settings_targets_configured_endpoint_and_index():
    settings = Settings(
        _env_file=None,
        azure_search_endpoint="https://example.search.windows.net",
        azure_search_index_name="fd-evidence",
    )
    service = SearchService.from_settings(settings)
    assert service.endpoint == "https://example.search.windows.net"
    assert service.index_name == "fd-evidence"
