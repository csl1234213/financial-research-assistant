"""Versioned Rust Chroma persistence contract, independent of Python clients."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def persistence_contract(service):
    """Official 1.5.9 /config.yaml default; legacy env is not its authority."""
    environment = service.get("environment", [])
    env = dict(item.split("=", 1) for item in environment)
    return (
        service.get("image") == "chromadb/chroma:1.5.9"
        and not service.get("command")
        and not service.get("entrypoint")
        and "PERSIST_DIRECTORY" not in env
        and "CHROMA_PERSIST_PATH" not in env
        and service.get("volumes") == ["chroma_data:/data"]
    )


def chroma():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["chromadb"]


def test_canonical_compose_uses_official_image_persistence_directory():
    assert persistence_contract(chroma())


@pytest.mark.parametrize("destination", ["/chroma/chroma", "/other-data"])
def test_wrong_mount_destination_rejected(destination):
    service = deepcopy(chroma())
    service["volumes"] = ["chroma_data:" + destination]
    assert not persistence_contract(service)


def test_legacy_env_cannot_be_persistence_authority():
    service = deepcopy(chroma())
    service["environment"].append("PERSIST_DIRECTORY=/data")
    assert not persistence_contract(service)
