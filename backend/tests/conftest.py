import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    """App wired to blank settings so tests never read a developer's backend/.env."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    return TestClient(app)
