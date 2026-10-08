from pathlib import Path

import docker.bootstrap_knowledge as bootstrap

CURRENT_PROFILE = (
    "intfloat/multilingual-e5-small",
    "revision",
    "parser",
    "chunker",
)


def test_expected_demo_sources_uses_pdf_files_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "Tesla_Q2_2025.pdf").write_bytes(b"pdf")
    (tmp_path / "README.md").write_text("not a document", encoding="utf-8")
    (tmp_path / "nested.pdf").mkdir()
    monkeypatch.setattr(bootstrap, "DEMO_PDF_DIR", tmp_path)

    assert bootstrap._expected_demo_sources() == {"Tesla_Q2_2025.pdf"}


def test_private_chroma_data_does_not_skip_public_bootstrap(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        bootstrap,
        "_expected_demo_sources",
        lambda: {"Tesla_Q2_2025.pdf"},
    )
    source_snapshots = iter([set(), {"Tesla_Q2_2025.pdf"}])
    monkeypatch.setattr(
        bootstrap,
        "_indexed_public_sources",
        lambda: next(source_snapshots),
    )
    profile_snapshots = iter([set(), {CURRENT_PROFILE}])
    monkeypatch.setattr(
        bootstrap,
        "_indexed_public_profiles",
        lambda: next(profile_snapshots),
    )
    monkeypatch.setattr(
        bootstrap,
        "_current_embedding_profile",
        lambda: CURRENT_PROFILE,
    )

    refresh_calls: list[bool] = []
    monkeypatch.setattr(
        "core.core_engine.refresh_knowledge_base",
        lambda: refresh_calls.append(True),
    )

    bootstrap.bootstrap()

    assert refresh_calls == [True]


def test_complete_public_demo_corpus_skips_refresh(monkeypatch) -> None:
    expected = {"Tesla_Q2_2025.pdf", "Apple_Q2_2026.pdf"}
    monkeypatch.setattr(bootstrap, "_expected_demo_sources", lambda: expected)
    monkeypatch.setattr(bootstrap, "_indexed_public_sources", lambda: expected)
    monkeypatch.setattr(
        bootstrap,
        "_indexed_public_profiles",
        lambda: {CURRENT_PROFILE},
    )
    monkeypatch.setattr(
        bootstrap,
        "_current_embedding_profile",
        lambda: CURRENT_PROFILE,
    )

    refresh_calls: list[bool] = []
    monkeypatch.setattr(
        "core.core_engine.refresh_knowledge_base",
        lambda: refresh_calls.append(True),
    )

    bootstrap.bootstrap()

    assert refresh_calls == []


def test_deleted_public_source_triggers_refresh(monkeypatch) -> None:
    expected = {"Tesla_Q2_2025.pdf"}
    source_snapshots = iter(
        [
            {"Tesla_Q2_2025.pdf", "Deleted_Old_Report.pdf"},
            expected,
        ]
    )
    monkeypatch.setattr(bootstrap, "_expected_demo_sources", lambda: expected)
    monkeypatch.setattr(
        bootstrap,
        "_indexed_public_sources",
        lambda: next(source_snapshots),
    )
    monkeypatch.setattr(
        bootstrap,
        "_indexed_public_profiles",
        lambda: {CURRENT_PROFILE},
    )
    monkeypatch.setattr(
        bootstrap,
        "_current_embedding_profile",
        lambda: CURRENT_PROFILE,
    )

    refresh_calls: list[bool] = []
    monkeypatch.setattr(
        "core.core_engine.refresh_knowledge_base",
        lambda: refresh_calls.append(True),
    )

    bootstrap.bootstrap()

    assert refresh_calls == [True]


def test_embedding_profile_change_triggers_refresh(monkeypatch) -> None:
    expected = {"Tesla_Q2_2025.pdf"}
    profile_snapshots = iter(
        [
            {("old-model", "old-revision", "old-parser", "old-chunker")},
            {CURRENT_PROFILE},
        ]
    )
    monkeypatch.setattr(bootstrap, "_expected_demo_sources", lambda: expected)
    monkeypatch.setattr(
        bootstrap,
        "_indexed_public_sources",
        lambda: expected,
    )
    monkeypatch.setattr(
        bootstrap,
        "_indexed_public_profiles",
        lambda: next(profile_snapshots),
    )
    monkeypatch.setattr(
        bootstrap,
        "_current_embedding_profile",
        lambda: CURRENT_PROFILE,
    )

    refresh_calls: list[bool] = []
    monkeypatch.setattr(
        "core.core_engine.refresh_knowledge_base",
        lambda: refresh_calls.append(True),
    )

    bootstrap.bootstrap()

    assert refresh_calls == [True]
