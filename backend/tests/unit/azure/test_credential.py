from azure.identity import DefaultAzureCredential

from app.azure.credential import get_credential


def test_get_credential_returns_default_azure_credential():
    get_credential.cache_clear()
    credential = get_credential()
    assert isinstance(credential, DefaultAzureCredential)


def test_get_credential_is_cached():
    get_credential.cache_clear()
    assert get_credential() is get_credential()
