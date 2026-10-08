"""Dry-run-safe LoRA training entry point.

This module keeps heavy ML imports inside the explicitly-confirmed execution
path.  Standard CI can therefore validate dataset and configuration contracts
without pulling a base model or attempting a training run.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import math
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

from training.config import LoRAConfig
from training.dataset import SupervisedDataset, load_supervised_dataset


class TrainingDependencyError(RuntimeError):
    """Raised only for an explicitly requested run missing optional ML extras."""


class TrainingSafetyError(RuntimeError):
    """Raised when a caller tries to start a real run without confirmation."""


@dataclass(frozen=True)
class DependencyStatus:
    package: str
    available: bool
    required: bool = True


@dataclass(frozen=True)
class TrainingReadiness:
    """Deterministic inspection result; it never imports model packages."""

    dataset_id: str
    record_count: int
    split_counts: Mapping[str, int]
    backend: str
    dependencies: tuple[DependencyStatus, ...]

    @property
    def is_ready_for_execution(self) -> bool:
        return all(not dependency.required or dependency.available for dependency in self.dependencies)

    @property
    def missing_dependencies(self) -> tuple[str, ...]:
        return tuple(
            dependency.package
            for dependency in self.dependencies
            if dependency.required and not dependency.available
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "record_count": self.record_count,
            "split_counts": dict(self.split_counts),
            "backend": self.backend,
            "is_ready_for_execution": self.is_ready_for_execution,
            "missing_dependencies": list(self.missing_dependencies),
            "dependencies": [
                {
                    "package": dependency.package,
                    "available": dependency.available,
                    "required": dependency.required,
                }
                for dependency in self.dependencies
            ],
        }


@dataclass(frozen=True)
class TrainingRunResult:
    """Auditable outcome that distinguishes validation from real training."""

    status: str
    actual_training_ran: bool
    readiness: TrainingReadiness
    output_dir: str | None = None
    duration_seconds: float | None = None
    metrics: Mapping[str, float] | None = None
    promotion_eligible: bool = False
    manifest_path: str | None = None
    model_card_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "actual_training_ran": self.actual_training_ran,
            "readiness": self.readiness.to_dict(),
            "output_dir": self.output_dir,
            "duration_seconds": self.duration_seconds,
            "metrics": dict(self.metrics or {}),
            "promotion_eligible": self.promotion_eligible,
            "manifest_path": self.manifest_path,
            "model_card_path": self.model_card_path,
        }


def inspect_training_readiness(config: LoRAConfig) -> TrainingReadiness:
    """Validate the corpus and report optional packages without importing them."""

    dataset = load_supervised_dataset(config.dataset_path)
    split_counts = {
        split: sum(1 for record in dataset.records if record.metadata.get("split", "train") == split)
        for split in ("train", "validation", "test")
    }
    split_counts = {split: count for split, count in split_counts.items() if count}
    dependencies = tuple(
        DependencyStatus(package=package, available=importlib.util.find_spec(package) is not None)
        for package in _required_packages(config)
    )
    return TrainingReadiness(
        dataset_id=dataset.dataset_id,
        record_count=len(dataset.records),
        split_counts=split_counts,
        backend=config.trainer_backend,
        dependencies=dependencies,
    )


def run_lora_training(
    config: LoRAConfig,
    *,
    dry_run: bool = True,
    confirm_training: bool = False,
) -> TrainingRunResult:
    """Validate or explicitly execute a LoRA fine-tuning job.

    The default is a no-network, no-GPU validation path.  ``dry_run=False``
    still refuses to run until ``confirm_training=True`` is supplied; this
    prevents accidental use from notebooks, test suites, or web handlers.
    """

    readiness = inspect_training_readiness(config)
    if dry_run:
        status = "dry_run_validated" if readiness.is_ready_for_execution else "dry_run_dependencies_missing"
        return TrainingRunResult(status=status, actual_training_ran=False, readiness=readiness)

    if not confirm_training:
        raise TrainingSafetyError(
            "A real LoRA run requires confirm_training=True; use the default dry_run first"
        )
    if not readiness.is_ready_for_execution:
        missing = ", ".join(readiness.missing_dependencies)
        raise TrainingDependencyError(
            f"Optional training dependencies are missing: {missing}. "
            "Install requirements/training.txt before requesting a real run."
        )

    started_at = perf_counter()
    dataset = load_supervised_dataset(config.dataset_path)
    if not dataset.split("validation"):
        raise TrainingSafetyError(
            "A confirmed training run requires an explicit validation split "
            "for the before/after evaluation gate"
        )
    output_dir, metrics = _run_confirmed_training(config, dataset)
    gated_metrics = _enforce_evaluation_gate(config, metrics)
    manifest_path, model_card_path = _write_adapter_evidence(
        config,
        dataset,
        output_dir,
        gated_metrics,
    )
    return TrainingRunResult(
        status="completed",
        actual_training_ran=True,
        readiness=readiness,
        output_dir=output_dir,
        duration_seconds=round(perf_counter() - started_at, 3),
        metrics=gated_metrics,
        promotion_eligible=True,
        manifest_path=str(manifest_path),
        model_card_path=str(model_card_path),
    )


def _required_packages(config: LoRAConfig) -> tuple[str, ...]:
    packages = ["torch", "transformers", "datasets", "peft", "accelerate"]
    if config.trainer_backend == "trl":
        packages.append("trl")
    if config.use_4bit:
        packages.append("bitsandbytes")
    return tuple(packages)


def _run_confirmed_training(config: LoRAConfig, dataset: SupervisedDataset) -> tuple[str, dict[str, float]]:
    """Import optional dependencies only after an explicit real-run request."""

    modules = _load_training_dependencies(config)
    if config.trainer_backend == "trl":
        return _run_trl_training(config, dataset, modules)
    return _run_transformers_training(config, dataset, modules)


def _enforce_evaluation_gate(
    config: LoRAConfig,
    metrics: Mapping[str, float],
) -> dict[str, float]:
    """Require the trained adapter to meet a deterministic promotion gate."""

    normalized = _numeric_metrics(metrics)
    baseline_loss = normalized.get("baseline_eval_loss")
    final_loss = normalized.get("final_eval_loss")
    if baseline_loss is None or final_loss is None:
        raise TrainingSafetyError(
            "Training did not produce baseline_eval_loss and final_eval_loss; "
            "the adapter cannot be promoted"
        )
    if not math.isfinite(baseline_loss) or not math.isfinite(final_loss):
        raise TrainingSafetyError(
            "Evaluation losses must be finite before an adapter can be promoted"
        )

    improvement = round(baseline_loss - final_loss, 6)
    normalized["eval_loss_improvement"] = improvement
    if improvement < config.min_eval_loss_improvement:
        raise TrainingSafetyError(
            "Adapter failed the evaluation gate: "
            f"eval loss improvement {improvement} is below the required "
            f"{config.min_eval_loss_improvement}"
        )
    return normalized


def _write_adapter_evidence(
    config: LoRAConfig,
    dataset: SupervisedDataset,
    output_dir: str,
    metrics: Mapping[str, float],
) -> tuple[Path, Path]:
    """Write a machine-readable manifest and a concise model card."""

    artifact_dir = Path(output_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = Path(config.dataset_path)
    dataset_digest = sha256(dataset_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "artifact_type": "peft_lora_adapter",
        "actual_training_ran": True,
        "promotion_eligible": True,
        "base_model_id": config.base_model_id,
        "dataset": {
            "id": dataset.dataset_id,
            "schema_version": dataset.schema_version,
            "sha256": dataset_digest,
            "record_count": len(dataset.records),
            "split_counts": {
                split: len(dataset.split(split))
                for split in ("train", "validation", "test")
                if dataset.split(split)
            },
        },
        "training_config": config.to_dict(),
        "evaluation_gate": {
            "metric": "eval_loss_improvement",
            "minimum": config.min_eval_loss_improvement,
            "actual": metrics["eval_loss_improvement"],
            "passed": True,
        },
        "metrics": dict(metrics),
        "limitations": [
            "Passing this gate does not establish financial factual accuracy.",
            "Run the versioned RAG and model benchmarks before serving the adapter.",
        ],
    }

    manifest_path = artifact_dir / "adapter_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    model_card_path = artifact_dir / "MODEL_CARD.md"
    model_card_path.write_text(
        _render_model_card(config, dataset, metrics, dataset_digest),
        encoding="utf-8",
    )
    return manifest_path, model_card_path


def _render_model_card(
    config: LoRAConfig,
    dataset: SupervisedDataset,
    metrics: Mapping[str, float],
    dataset_digest: str,
) -> str:
    return (
        "# Financial Assistant LoRA Adapter\n\n"
        "## Provenance\n\n"
        f"- Base model: `{config.base_model_id}`\n"
        f"- Dataset: `{dataset.dataset_id}`\n"
        f"- Dataset SHA-256: `{dataset_digest}`\n"
        f"- Trainer backend: `{config.trainer_backend}`\n"
        f"- Seed: `{config.seed}`\n\n"
        "## Promotion gate\n\n"
        f"- Baseline validation loss: `{metrics['baseline_eval_loss']}`\n"
        f"- Final validation loss: `{metrics['final_eval_loss']}`\n"
        f"- Improvement: `{metrics['eval_loss_improvement']}`\n"
        f"- Required improvement: `{config.min_eval_loss_improvement}`\n"
        "- Result: `passed`\n\n"
        "## Limitations\n\n"
        "This adapter is not independently validated for factual financial "
        "accuracy, investment suitability, or live retrieval quality. Run the "
        "versioned RAG and model evaluation suites before deployment.\n"
    )


def _load_training_dependencies(config: LoRAConfig) -> dict[str, Any]:
    try:
        modules = {
            "torch": importlib.import_module("torch"),
            "datasets": importlib.import_module("datasets"),
            "peft": importlib.import_module("peft"),
            "transformers": importlib.import_module("transformers"),
            "accelerate": importlib.import_module("accelerate"),
        }
        if config.trainer_backend == "trl":
            modules["trl"] = importlib.import_module("trl")
        if config.use_4bit:
            modules["bitsandbytes"] = importlib.import_module("bitsandbytes")
    except ImportError as exc:
        raise TrainingDependencyError(
            "Unable to import an optional training dependency. "
            "Install requirements/training.txt and retry an explicitly confirmed run."
        ) from exc
    return modules


def _build_peft_config(config: LoRAConfig, peft: Any) -> Any:
    task_type = getattr(peft.TaskType, "CAUSAL_LM")
    return peft.LoraConfig(
        task_type=task_type,
        r=config.rank,
        lora_alpha=config.alpha,
        lora_dropout=config.dropout,
        target_modules=list(config.target_modules),
        bias="none",
    )


def _model_load_kwargs(config: LoRAConfig) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"trust_remote_code": config.trust_remote_code}
    if config.use_4bit:
        kwargs["load_in_4bit"] = True
        kwargs["device_map"] = config.device_map or "auto"
    elif config.device_map:
        kwargs["device_map"] = config.device_map
    return kwargs


def _dataset_rows(dataset: SupervisedDataset) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    train_rows: list[dict[str, str]] = []
    validation_rows: list[dict[str, str]] = []
    for record in dataset.records:
        row = {"text": record.format_for_causal_lm()}
        if record.metadata.get("split", "train") == "validation":
            validation_rows.append(row)
        elif record.metadata.get("split", "train") == "train":
            train_rows.append(row)

    if not train_rows:
        raise TrainingSafetyError("Training dataset has no records with metadata.split='train'")
    return train_rows, validation_rows


def _build_training_arguments(config: LoRAConfig, transformers: Any, has_validation: bool) -> Any:
    arguments = {
        "output_dir": config.output_dir,
        "num_train_epochs": config.num_train_epochs,
        "per_device_train_batch_size": config.per_device_train_batch_size,
        "per_device_eval_batch_size": config.per_device_train_batch_size,
        "gradient_accumulation_steps": config.gradient_accumulation_steps,
        "learning_rate": config.learning_rate,
        "logging_steps": 10,
        "save_strategy": "epoch",
        "report_to": [],
        "seed": config.seed,
        "remove_unused_columns": False,
    }
    if has_validation:
        try:
            return transformers.TrainingArguments(eval_strategy="epoch", **arguments)
        except TypeError:
            return transformers.TrainingArguments(evaluation_strategy="epoch", **arguments)
    return transformers.TrainingArguments(**arguments)


def _run_transformers_training(
    config: LoRAConfig,
    dataset: SupervisedDataset,
    modules: Mapping[str, Any],
) -> tuple[str, dict[str, float]]:
    transformers = modules["transformers"]
    peft = modules["peft"]
    dataset_module = modules["datasets"]

    train_rows, validation_rows = _dataset_rows(dataset)
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        config.base_model_id,
        trust_remote_code=config.trust_remote_code,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    if tokenizer.pad_token_id is None:
        raise TrainingSafetyError("The selected tokenizer has no pad_token or eos_token")

    def tokenize(batch: Mapping[str, list[str]]) -> dict[str, Any]:
        encoded = tokenizer(
            batch["text"],
            truncation=True,
            max_length=config.max_seq_length,
            padding="max_length",
        )
        encoded["labels"] = [
            [token if mask else -100 for token, mask in zip(tokens, mask_values)]
            for tokens, mask_values in zip(encoded["input_ids"], encoded["attention_mask"])
        ]
        return encoded

    train_dataset = dataset_module.Dataset.from_list(train_rows).map(tokenize, batched=True)
    eval_dataset = (
        dataset_module.Dataset.from_list(validation_rows).map(tokenize, batched=True)
        if validation_rows
        else None
    )
    model = transformers.AutoModelForCausalLM.from_pretrained(
        config.base_model_id,
        **_model_load_kwargs(config),
    )
    model.config.use_cache = False
    model = peft.get_peft_model(model, _build_peft_config(config, peft))

    training_arguments = _build_training_arguments(config, transformers, eval_dataset is not None)
    trainer_kwargs = {
        "model": model,
        "args": training_arguments,
        "train_dataset": train_dataset,
        "eval_dataset": eval_dataset,
        "data_collator": transformers.default_data_collator,
    }
    try:
        trainer = transformers.Trainer(processing_class=tokenizer, **trainer_kwargs)
    except TypeError:
        trainer = transformers.Trainer(tokenizer=tokenizer, **trainer_kwargs)
    baseline_loss = _evaluate_validation_loss(trainer, "baseline")
    train_output = trainer.train()
    final_loss = _evaluate_validation_loss(trainer, "final")

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    metrics = _numeric_metrics(getattr(train_output, "metrics", {}))
    metrics["baseline_eval_loss"] = baseline_loss
    metrics["final_eval_loss"] = final_loss
    return str(output_dir), metrics


def _run_trl_training(
    config: LoRAConfig,
    dataset: SupervisedDataset,
    modules: Mapping[str, Any],
) -> tuple[str, dict[str, float]]:
    """Run SFTTrainer while adapting to its documented API name changes."""

    import inspect

    transformers = modules["transformers"]
    peft = modules["peft"]
    dataset_module = modules["datasets"]
    trl = modules["trl"]
    train_rows, validation_rows = _dataset_rows(dataset)
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        config.base_model_id,
        trust_remote_code=config.trust_remote_code,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    if tokenizer.pad_token_id is None:
        raise TrainingSafetyError("The selected tokenizer has no pad_token or eos_token")

    model = transformers.AutoModelForCausalLM.from_pretrained(
        config.base_model_id,
        **_model_load_kwargs(config),
    )
    model.config.use_cache = False
    training_arguments = _build_training_arguments(config, transformers, bool(validation_rows))
    sft_parameters = inspect.signature(trl.SFTTrainer.__init__).parameters
    trainer_kwargs: dict[str, Any] = {
        "model": model,
        "args": training_arguments,
        "train_dataset": dataset_module.Dataset.from_list(train_rows),
        "eval_dataset": dataset_module.Dataset.from_list(validation_rows) if validation_rows else None,
        "peft_config": _build_peft_config(config, peft),
    }
    if "processing_class" in sft_parameters:
        trainer_kwargs["processing_class"] = tokenizer
    elif "tokenizer" in sft_parameters:
        trainer_kwargs["tokenizer"] = tokenizer
    if "dataset_text_field" in sft_parameters:
        trainer_kwargs["dataset_text_field"] = "text"
    if "max_seq_length" in sft_parameters:
        trainer_kwargs["max_seq_length"] = config.max_seq_length
    elif "max_length" in sft_parameters:
        trainer_kwargs["max_length"] = config.max_seq_length

    trainer = trl.SFTTrainer(**trainer_kwargs)
    baseline_loss = _evaluate_validation_loss(trainer, "baseline")
    train_output = trainer.train()
    final_loss = _evaluate_validation_loss(trainer, "final")
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    metrics = _numeric_metrics(getattr(train_output, "metrics", {}))
    metrics["baseline_eval_loss"] = baseline_loss
    metrics["final_eval_loss"] = final_loss
    return str(output_dir), metrics


def _evaluate_validation_loss(trainer: Any, prefix: str) -> float:
    """Run one explicit validation pass and return its finite loss."""

    try:
        raw_metrics = trainer.evaluate(metric_key_prefix=prefix)
    except TypeError:
        raw_metrics = trainer.evaluate()
    metrics = _numeric_metrics(raw_metrics)
    loss = metrics.get(f"{prefix}_loss", metrics.get("eval_loss"))
    if loss is None or not math.isfinite(loss):
        raise TrainingSafetyError(
            f"{prefix} validation did not produce a finite loss"
        )
    return loss


def _numeric_metrics(metrics: Any) -> dict[str, float]:
    if not isinstance(metrics, Mapping):
        return {}
    return {
        str(key): round(float(value), 6)
        for key, value in metrics.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
