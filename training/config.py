"""Configuration contract for an explicitly-confirmed LoRA training run."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping


class LoRAConfigurationError(ValueError):
    """Raised when a LoRA configuration would be unsafe or invalid."""


@dataclass(frozen=True)
class LoRAConfig:
    """Portable configuration for a supervised causal-LM LoRA job.

    ``run_lora_training`` is dry-run by default.  A real run additionally
    requires an explicit confirmation argument, so merely loading this config
    cannot download a model, allocate a GPU, or create an adapter artifact.
    """

    dataset_path: str
    base_model_id: str
    output_dir: str = "artifacts/lora"
    target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj")
    rank: int = 16
    alpha: int = 32
    dropout: float = 0.05
    learning_rate: float = 2e-4
    num_train_epochs: float = 1.0
    per_device_train_batch_size: int = 1
    gradient_accumulation_steps: int = 8
    max_seq_length: int = 1024
    seed: int = 42
    trainer_backend: Literal["transformers", "trl"] = "transformers"
    use_4bit: bool = False
    device_map: str | None = None
    trust_remote_code: bool = False
    min_eval_loss_improvement: float = 0.0

    def __post_init__(self) -> None:
        if not self.dataset_path.strip():
            raise LoRAConfigurationError("dataset_path must be non-empty")
        if not self.base_model_id.strip():
            raise LoRAConfigurationError("base_model_id must be non-empty")
        if not self.output_dir.strip():
            raise LoRAConfigurationError("output_dir must be non-empty")
        if not self.target_modules or any(not module.strip() for module in self.target_modules):
            raise LoRAConfigurationError("target_modules must contain at least one non-empty module name")
        if not 1 <= self.rank <= 256:
            raise LoRAConfigurationError("rank must be between 1 and 256")
        if self.alpha <= 0:
            raise LoRAConfigurationError("alpha must be positive")
        if not 0 <= self.dropout < 1:
            raise LoRAConfigurationError("dropout must be in [0, 1)")
        if self.learning_rate <= 0:
            raise LoRAConfigurationError("learning_rate must be positive")
        if self.num_train_epochs <= 0:
            raise LoRAConfigurationError("num_train_epochs must be positive")
        if self.per_device_train_batch_size < 1 or self.gradient_accumulation_steps < 1:
            raise LoRAConfigurationError("batch size and gradient accumulation must be at least one")
        if not 64 <= self.max_seq_length <= 32_768:
            raise LoRAConfigurationError("max_seq_length must be between 64 and 32768")
        if self.trainer_backend not in {"transformers", "trl"}:
            raise LoRAConfigurationError("trainer_backend must be 'transformers' or 'trl'")
        if self.min_eval_loss_improvement < 0:
            raise LoRAConfigurationError(
                "min_eval_loss_improvement must be non-negative"
            )

    @classmethod
    def from_mapping(cls, raw_config: Mapping[str, Any]) -> "LoRAConfig":
        """Strictly parse a JSON/YAML-derived configuration mapping."""

        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        unknown = sorted(set(raw_config) - allowed)
        if unknown:
            raise LoRAConfigurationError(f"Unsupported LoRA config fields: {', '.join(unknown)}")
        values = dict(raw_config)
        if "target_modules" in values and isinstance(values["target_modules"], list):
            values["target_modules"] = tuple(values["target_modules"])
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable config metadata for an experiment report."""

        data = asdict(self)
        data["target_modules"] = list(self.target_modules)
        return data
