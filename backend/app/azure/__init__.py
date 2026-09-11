"""Thin, keyless wrappers around the Azure SDK clients this app depends on.

Each module exposes one service class with a ``from_settings`` factory. Everything authenticates
with ``DefaultAzureCredential`` (see ``credential.py``) - there are no API keys in this package.
Business logic (chunking, indexing, review orchestration) lives in ``app.services``, not here.
"""
