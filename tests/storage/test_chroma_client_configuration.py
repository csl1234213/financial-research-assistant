from unittest.mock import Mock

import pytest

from storage.chroma_store import ChromaEmbeddingStore
from storage.exceptions import EmbeddingStoreError


def test_uses_persistent_client_when_http_host_is_not_configured(monkeypatch, tmp_path):
    persistent_client = Mock()
    persistent_factory = Mock(return_value=persistent_client)
    http_factory = Mock()
    monkeypatch.delenv("CHROMA_HOST", raising=False)
    monkeypatch.setattr("storage.chroma_store.chromadb.PersistentClient", persistent_factory)
    monkeypatch.setattr("storage.chroma_store.chromadb.HttpClient", http_factory)

    store = ChromaEmbeddingStore(persist_directory=tmp_path)

    assert store.mode == "persistent"
    assert store.client is persistent_client
    persistent_factory.assert_called_once_with(path=str(tmp_path))
    http_factory.assert_not_called()


def test_uses_http_client_from_explicit_configuration(monkeypatch):
    http_client = Mock()
    http_factory = Mock(return_value=http_client)
    persistent_factory = Mock()
    monkeypatch.setattr("storage.chroma_store.chromadb.HttpClient", http_factory)
    monkeypatch.setattr("storage.chroma_store.chromadb.PersistentClient", persistent_factory)

    store = ChromaEmbeddingStore(host="chroma.internal", port=9000, ssl=True)

    assert store.mode == "http"
    assert store.client is http_client
    http_factory.assert_called_once_with(host="chroma.internal", port=9000, ssl=True)
    persistent_factory.assert_not_called()


def test_uses_http_client_from_environment(monkeypatch):
    http_factory = Mock(return_value=Mock())
    monkeypatch.setenv("CHROMA_HOST", "chromadb")
    monkeypatch.setenv("CHROMA_PORT", "8000")
    monkeypatch.setenv("CHROMA_SSL", "false")
    monkeypatch.setattr("storage.chroma_store.chromadb.HttpClient", http_factory)

    store = ChromaEmbeddingStore()

    assert store.mode == "http"
    http_factory.assert_called_once_with(host="chromadb", port=8000, ssl=False)


def test_invalid_http_port_fails_with_storage_error(monkeypatch):
    monkeypatch.setenv("CHROMA_HOST", "chromadb")
    monkeypatch.setenv("CHROMA_PORT", "not-a-port")

    with pytest.raises(EmbeddingStoreError, match="CHROMA_PORT must be an integer"):
        ChromaEmbeddingStore()


def test_context_manager_closes_the_underlying_client(monkeypatch, tmp_path):
    persistent_client = Mock()
    monkeypatch.delenv("CHROMA_HOST", raising=False)
    monkeypatch.setattr(
        "storage.chroma_store.chromadb.PersistentClient",
        Mock(return_value=persistent_client),
    )

    with ChromaEmbeddingStore(persist_directory=tmp_path):
        pass

    persistent_client.close.assert_called_once_with()


def test_production_mode_without_chroma_host_fails_fast(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("CHROMA_HOST", raising=False)

    with pytest.raises(
        EmbeddingStoreError,
        match="CHROMA_HOST must be set in production",
    ):
        ChromaEmbeddingStore()


def test_production_mode_with_chroma_host_uses_http_client(monkeypatch):
    http_client = Mock()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CHROMA_HOST", "chromadb")
    monkeypatch.setenv("CHROMA_PORT", "8000")
    monkeypatch.setattr(
        "storage.chroma_store.chromadb.HttpClient",
        Mock(return_value=http_client),
    )

    store = ChromaEmbeddingStore()

    assert store.mode == "http"
    assert store.client is http_client


def test_explicit_host_parameter_overrides_environment(monkeypatch):
    explicit_client = Mock()
    http_factory = Mock(return_value=explicit_client)
    monkeypatch.setenv("CHROMA_HOST", "from-env")
    monkeypatch.setenv("CHROMA_PORT", "9999")
    monkeypatch.setattr("storage.chroma_store.chromadb.HttpClient", http_factory)

    store = ChromaEmbeddingStore(host="explicit-host", port=7000)

    assert store.mode == "http"
    http_factory.assert_called_once_with(host="explicit-host", port=7000, ssl=False)


def test_port_out_of_range_fails_with_storage_error(monkeypatch):
    monkeypatch.setenv("CHROMA_HOST", "chromadb")
    monkeypatch.setenv("CHROMA_PORT", "99999")

    with pytest.raises(
        EmbeddingStoreError,
        match="CHROMA_PORT must be between 1 and 65535",
    ):
        ChromaEmbeddingStore()
