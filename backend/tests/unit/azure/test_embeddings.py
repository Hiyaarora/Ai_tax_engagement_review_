import pytest

from app.azure.embeddings import EMBEDDING_DIMENSIONS, EmbeddingService
from app.config import Settings


class _FakeEmbeddingsApi:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, *, model: str, input: list[str]):
        self.calls.append({"model": model, "input": input})

        class _Item:
            def __init__(self, i: int) -> None:
                self.index = i
                self.embedding = [float(i)] * 3

        class _Response:
            # Returned out of order to prove the service sorts by index.
            data = [_Item(i) for i in reversed(range(len(input)))]

        return _Response()


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.embeddings = _FakeEmbeddingsApi()


def _service(client: _FakeOpenAIClient) -> EmbeddingService:
    return EmbeddingService(client=client, deployment="text-embedding-3-small")  # type: ignore[arg-type]


def test_embed_returns_one_vector_per_input_in_input_order():
    client = _FakeOpenAIClient()

    vectors = _service(client).embed(["alpha", "beta", "gamma"])

    assert vectors == [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [2.0, 2.0, 2.0]]
    assert client.embeddings.calls[0] == {
        "model": "text-embedding-3-small",
        "input": ["alpha", "beta", "gamma"],
    }


def test_embed_empty_input_makes_no_api_call():
    client = _FakeOpenAIClient()
    assert _service(client).embed([]) == []
    assert client.embeddings.calls == []


def test_embed_rejects_blank_strings():
    with pytest.raises(ValueError, match="blank"):
        _service(_FakeOpenAIClient()).embed(["ok", "   "])


def test_embedding_dimensions_match_text_embedding_3_small():
    assert EMBEDDING_DIMENSIONS == 1536


def test_from_settings_uses_configured_deployment():
    settings = Settings(
        _env_file=None,
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        foundry_embedding_deployment="text-embedding-3-small",
    )
    service = EmbeddingService.from_settings(settings)
    assert service.deployment == "text-embedding-3-small"


def test_from_settings_targets_resource_level_openai_v1_route():
    """The project-scoped /api/projects/<name>/openai/v1 route 404s; resource-level works."""
    settings = Settings(
        _env_file=None,
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/my-proj",
    )
    service = EmbeddingService.from_settings(settings)
    assert str(service.base_url) == "https://example.services.ai.azure.com/openai/v1/"


def test_from_settings_applies_timeout_and_retry_budget():
    settings = Settings(
        _env_file=None,
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        openai_timeout_seconds=45,
        openai_max_retries=1,
    )
    service = EmbeddingService.from_settings(settings)
    assert service._client.timeout == 45 and service._client.max_retries == 1
