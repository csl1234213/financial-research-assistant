"""A small, deterministic prompt registry for versioned prompt assets."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Mapping


class PromptNotFound(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    name: str
    version: str
    content: str
    system_prompt: str = ""
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def checksum(self) -> str:
        canonical = (
            f"system:\n{self.system_prompt}\n"
            f"user-template:\n{self.content}"
        )
        return sha256(canonical.encode("utf-8")).hexdigest()


class PromptRegistry:
    """In-process registry with explicit name/version lookup.

    Prompt assets live in source control; the checksum is emitted with runtime
    metadata so an evaluation report can be tied to the exact instructions.
    """

    _definitions: dict[tuple[str, str], PromptDefinition] = {}

    @classmethod
    def register(cls, definition: PromptDefinition) -> None:
        key = (definition.name, definition.version)
        existing = cls._definitions.get(key)
        if existing is not None and existing.checksum != definition.checksum:
            raise ValueError(f"Prompt {definition.name}@{definition.version} is immutable")
        cls._definitions[key] = definition

    @classmethod
    def get(cls, name: str, version: str) -> PromptDefinition:
        try:
            return cls._definitions[(name, version)]
        except KeyError as exc:
            raise PromptNotFound(f"Prompt {name}@{version} is not registered") from exc

    @classmethod
    def metadata(cls, name: str, version: str) -> Mapping[str, str]:
        definition = cls.get(name, version)
        return {
            "name": definition.name,
            "version": definition.version,
            "checksum": definition.checksum,
            "system_checksum": sha256(
                definition.system_prompt.encode("utf-8")
            ).hexdigest(),
        }

    @classmethod
    def list_versions(cls, name: str) -> list[str]:
        return sorted(version for prompt_name, version in cls._definitions if prompt_name == name)
