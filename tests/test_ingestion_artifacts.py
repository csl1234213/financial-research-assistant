import hashlib

import pytest

from storage.ingestion_artifacts import IngestionArtifactStore


def test_real_pdf_artifact_survives_restart(tmp_path):
    from pathlib import Path

    content = (Path(__file__).parent / "fixtures/moutai-standard-statements-2025.pdf").read_bytes()
    source = hashlib.sha256(content).hexdigest()
    digest = IngestionArtifactStore(tmp_path).put(1, source, content)
    assert IngestionArtifactStore(tmp_path).read(1, source, digest) == content
    with pytest.raises(FileNotFoundError):
        IngestionArtifactStore(tmp_path).read(2, source, digest)


def test_corrupt_artifact_is_rejected(tmp_path):
    store = IngestionArtifactStore(tmp_path)
    source = "a" * 64
    digest = store.put(1, source, b"original")
    (tmp_path / "1" / source / digest).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="INTEGRITY"):
        store.read(1, source, digest)


@pytest.mark.parametrize("owner,source", [(True, "a" * 64), (0, "a" * 64), (1, "../escape")])
def test_invalid_artifact_identity(tmp_path, owner, source):
    with pytest.raises(ValueError):
        IngestionArtifactStore(tmp_path).put(owner, source, b"content")
