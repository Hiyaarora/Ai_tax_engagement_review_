"""Single shared Azure credential.

Locally this resolves to your ``az login`` identity; in Azure it resolves to Managed Identity.
The interactive-browser fallback is disabled so a misconfigured server never blocks on a login.
"""

from functools import lru_cache

from azure.identity import DefaultAzureCredential


@lru_cache
def get_credential() -> DefaultAzureCredential:
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)
