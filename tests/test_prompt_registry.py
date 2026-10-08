import pytest

from prompt_builder import (
    DIRECT_CHAT_PROMPT_VERSION,
    FINANCIAL_COMPARE_PROMPT_VERSION,
    FINANCIAL_RAG_PROMPT_VERSION,
    FINANCIAL_RAG_TEMPLATE,
    FINANCIAL_SYSTEM_PROMPT,
    get_prompt_metadata,
)
from prompts.registry import PromptDefinition, PromptRegistry


def test_built_in_prompts_expose_versioned_metadata():
    rag = get_prompt_metadata("financial_rag")
    compare = get_prompt_metadata("financial_compare")
    direct = get_prompt_metadata("direct_chat")

    assert rag["version"] == FINANCIAL_RAG_PROMPT_VERSION
    assert compare["version"] == FINANCIAL_COMPARE_PROMPT_VERSION
    assert direct["version"] == DIRECT_CHAT_PROMPT_VERSION
    assert len(rag["checksum"]) == 64
    assert len(rag["system_checksum"]) == 64


def test_prompt_checksum_covers_system_and_complete_user_template():
    registered = PromptRegistry.get(
        "financial_rag",
        FINANCIAL_RAG_PROMPT_VERSION,
    )

    assert registered.system_prompt == FINANCIAL_SYSTEM_PROMPT
    assert registered.content == FINANCIAL_RAG_TEMPLATE
    assert "RESPONSE FORMAT" in registered.content


def test_prompt_versions_are_immutable():
    definition = PromptDefinition(name="test_prompt", version="1.0.0", content="first")
    PromptRegistry.register(definition)

    with pytest.raises(ValueError, match="immutable"):
        PromptRegistry.register(
            PromptDefinition(name="test_prompt", version="1.0.0", content="changed")
        )
