import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import torch


@pytest.mark.unit
class TestGetCachePath:
    def test_returns_cache_path_with_folder_name(self):
        from embedding import get_cache_path
        path = get_cache_path("data/pdfs")
        assert "cache" in path
        assert path.endswith(".pt")

    def test_empty_folder_name_uses_default(self):
        from embedding import get_cache_path
        path = get_cache_path("")
        assert "all_documents.pt" in path

    def test_trailing_slash_handled(self):
        from embedding import get_cache_path
        path = get_cache_path("data/pdfs/")
        assert path.endswith(".pt")


@pytest.mark.unit
class TestLoadCachedEmbeddings:
    def test_returns_none_when_not_exists(self):
        from embedding import load_cached_embeddings
        result = load_cached_embeddings("/nonexistent/path/cache.pt")
        assert result is None

    def test_loads_existing_cache(self):
        from embedding import load_cached_embeddings
        with tempfile.NamedTemporaryFile(suffix=".pt", delete=False) as f:
            tensor = torch.tensor([1.0, 2.0, 3.0])
            torch.save(tensor, f.name)

        try:
            result = load_cached_embeddings(f.name)
            assert result is not None
            assert torch.equal(result, tensor)
        finally:
            os.unlink(f.name)


@pytest.mark.unit
class TestSaveEmbeddings:
    def test_saves_to_path(self):
        from embedding import save_embeddings
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = os.path.join(tmpdir, "subdir", "cache.pt")
            tensor = torch.tensor([1.0, 2.0])
            save_embeddings(save_path, tensor)
            assert os.path.exists(save_path)

    def test_saved_data_is_correct(self):
        from embedding import save_embeddings
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = os.path.join(tmpdir, "cache.pt")
            tensor = torch.tensor([1.0, 2.0, 3.0])
            save_embeddings(save_path, tensor)
            loaded = torch.load(save_path)
            assert torch.equal(loaded, tensor)


@pytest.mark.unit
class TestLoadEmbeddingModel:
    @patch("embedding.SentenceTransformer")
    def test_loads_model_with_correct_name(self, mock_st):
        from config import EMBEDDING_MODEL_REVISION
        from embedding import load_embedding_model

        load_embedding_model(force_reload=True)
        mock_st.assert_called_once_with(
            "intfloat/multilingual-e5-small",
            revision=EMBEDDING_MODEL_REVISION,
        )

    @patch("embedding.SentenceTransformer")
    def test_returns_model_instance(self, mock_st):
        from embedding import load_embedding_model
        mock_model = MagicMock()
        mock_st.return_value = mock_model
        result = load_embedding_model(force_reload=True)
        assert result is mock_model

    @patch("embedding.SentenceTransformer")
    def test_reuses_process_local_model(self, mock_st):
        from embedding import load_embedding_model

        model = MagicMock()
        mock_st.return_value = model
        first = load_embedding_model(force_reload=True)
        second = load_embedding_model()

        assert first is second
        mock_st.assert_called_once()

    @patch("embedding.SentenceTransformer")
    def test_status_does_not_trigger_model_loading(self, mock_st):
        import embedding

        embedding._model = None
        embedding._model_error_type = None

        status = embedding.get_embedding_model_status()

        assert status["state"] == "not_loaded"
        assert status["model"] == "intfloat/multilingual-e5-small"
        mock_st.assert_not_called()


@pytest.mark.unit
class TestEmbedChunks:
    @patch("embedding.SentenceTransformer")
    def test_encodes_texts_from_chunks(self, mock_st):
        from embedding import embed_chunks
        mock_model = MagicMock()
        mock_model.encode.return_value = torch.tensor([[0.1, 0.2], [0.3, 0.4]])
        chunks = [
            {"text": "Apple revenue grew 10%", "metadata": {"company": "Apple"}},
            {"text": "Tesla delivered 1.8M vehicles", "metadata": {"company": "Tesla"}},
        ]
        embed_chunks(mock_model, chunks)
        mock_model.encode.assert_called_once()
        call = mock_model.encode.call_args
        assert call.args[0] == [
            "passage: Apple revenue grew 10%",
            "passage: Tesla delivered 1.8M vehicles",
        ]
        assert call.kwargs["convert_to_tensor"] is True
        assert call.kwargs["normalize_embeddings"] is True
        assert call.kwargs["batch_size"] > 0

    @patch("embedding.SentenceTransformer")
    def test_returns_tensor(self, mock_st):
        from embedding import embed_chunks
        mock_model = MagicMock()
        mock_model.encode.return_value = torch.tensor([[0.1, 0.2]])
        chunks = [{"text": "test"}]
        result = embed_chunks(mock_model, chunks)
        assert isinstance(result, torch.Tensor)

    @patch("embedding.SentenceTransformer")
    def test_returns_correct_shape(self, mock_st):
        from embedding import embed_chunks
        mock_model = MagicMock()
        mock_model.encode.return_value = torch.tensor([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        chunks = [{"text": "a"}, {"text": "b"}]
        result = embed_chunks(mock_model, chunks)
        assert result.shape == (2, 3)

    def test_query_uses_e5_prefix_and_normalization(self):
        from embedding import embed_query

        mock_model = MagicMock()
        mock_model.encode.return_value = torch.tensor([0.1, 0.2])

        embed_query(mock_model, "特斯拉营收增长")

        mock_model.encode.assert_called_once_with(
            "query: 特斯拉营收增长",
            convert_to_tensor=False,
            normalize_embeddings=True,
        )


@pytest.mark.unit
class TestGetEmbeddings:
    @patch("embedding.embed_chunks")
    @patch("embedding.load_cached_embeddings")
    def test_returns_cache_when_present(self, mock_load, mock_embed):
        from embedding import get_embeddings
        cached = torch.tensor([[1.0, 2.0]])
        mock_load.return_value = cached

        result = get_embeddings(MagicMock(), [{"text": "test"}], "data/pdfs")
        assert result is cached
        mock_embed.assert_not_called()

    @patch("embedding.save_embeddings")
    @patch("embedding.embed_chunks")
    @patch("embedding.load_cached_embeddings")
    def test_embeds_and_saves_when_no_cache(self, mock_load, mock_embed, mock_save):
        from embedding import get_embeddings
        mock_load.return_value = None
        new_embeddings = torch.tensor([[1.0, 2.0]])
        mock_embed.return_value = new_embeddings

        result = get_embeddings(MagicMock(), [{"text": "test"}], "data/pdfs")
        assert result is new_embeddings
        mock_embed.assert_called_once()
        mock_save.assert_called_once()
