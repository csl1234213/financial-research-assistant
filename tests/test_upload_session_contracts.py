from datetime import timedelta

import pytest

from core.upload_session_contracts import UploadState
from tests.formal_contract_data import HASH, NOW, session, verifying


@pytest.mark.EXPERIMENTAL
def test_trusted_progress_is_monotonic_and_serializable():
    from dataclasses import replace

    from storage.upload_session_pilot import _decode, _encode

    value = replace(session(), protocol="tus").transition(UploadState.UPLOADING, NOW)
    later = NOW + timedelta(seconds=10)
    value = value.observe_transport_progress(offset=80, now=later)
    value = value.observe_transport_progress(offset=20, now=NOW)
    assert value.bytes_received == 80
    assert value.updated_at == later
    assert _decode(_encode(value)) == value


@pytest.mark.parametrize("offset", [-1, 101, True, 1.5])
def test_invalid_transport_offsets_rejected(offset):
    from dataclasses import replace

    value = replace(session(), protocol="tus").transition(UploadState.UPLOADING, NOW)
    with pytest.raises(ValueError, match="INVALID_RECEIVED_BYTES"):
        value.observe_transport_progress(offset=offset, now=NOW)


@pytest.mark.EXPERIMENTAL
def test_legacy_payload_remains_readable():
    import json

    from storage.upload_session_pilot import _decode, _encode

    data = json.loads(_encode(session()))
    del data["updated_at"]
    del data["bytes_received"]
    value = _decode(json.dumps(data))
    assert value.updated_at == NOW
    assert value.bytes_received == 0


def test_verified_finalize_is_identity_stable_not_document_ready():
    value = verifying().verify(size=100, sha256=HASH, pdf_magic_valid=True, now=NOW)
    result = value.finalize(document_id="doc-1", ingestion_job_id="job-1", now=NOW)
    assert result.state == UploadState.FINALIZED
    assert result.finalize(document_id="doc-1", ingestion_job_id="job-1", now=NOW) is result
    with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
        result.finalize(document_id="doc-2", ingestion_job_id="job-1", now=NOW)


@pytest.mark.parametrize("size,sha256,magic", [(99, HASH, True), (100, "b" * 64, True), (100, HASH, False)])
def test_corrupt_content_cannot_finalize(size, sha256, magic):
    value = verifying().verify(size=size, sha256=sha256, pdf_magic_valid=magic, now=NOW)
    assert value.state == UploadState.FAILED
    with pytest.raises(ValueError):
        value.finalize(document_id="doc", ingestion_job_id="job", now=NOW)


@pytest.mark.parametrize("tenant,user", [(2, 2), (1, 3)])
def test_ownership_is_both_user_and_tenant(tenant, user):
    with pytest.raises(PermissionError):
        session().authorize(tenant, user)


def test_expiry_and_skip_are_rejected():
    with pytest.raises(ValueError, match="ILLEGAL_TRANSITION"):
        session().transition(UploadState.UPLOADED, NOW)
    with pytest.raises(ValueError, match="UPLOAD_EXPIRED"):
        session().transition(UploadState.UPLOADING, NOW + timedelta(hours=2))
    assert session().transition(UploadState.EXPIRED, NOW + timedelta(hours=2)).state == UploadState.EXPIRED
