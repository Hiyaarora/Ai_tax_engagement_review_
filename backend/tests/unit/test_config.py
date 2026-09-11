from app.config import Settings


def test_defaults_are_safe_for_local_dev():
    settings = Settings(_env_file=None)
    assert settings.app_env == "development"
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.foundry_configured is False
    assert settings.search_configured is False
    assert settings.document_intelligence_configured is False


def test_configured_flags_flip_when_endpoints_present():
    settings = Settings(
        _env_file=None,
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        foundry_agent_id="asst_123",
        azure_search_endpoint="https://example.search.windows.net",
        azure_document_intelligence_endpoint="https://example.cognitiveservices.azure.com/",
    )
    assert settings.foundry_configured is True
    assert settings.search_configured is True
    assert settings.document_intelligence_configured is True


def test_cors_origins_parse_from_comma_separated_string():
    settings = Settings(_env_file=None, cors_origins="http://a.test, http://b.test")
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_foundry_resource_endpoint_is_derived_from_project_endpoint():
    settings = Settings(
        _env_file=None,
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/my-proj",
    )
    assert settings.foundry_resource_endpoint == "https://example.services.ai.azure.com"


def test_foundry_resource_endpoint_is_empty_when_project_endpoint_unset():
    assert Settings(_env_file=None).foundry_resource_endpoint == ""
