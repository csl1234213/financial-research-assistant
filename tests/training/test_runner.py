import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from training import (
    LoRAConfig,
    TrainingDependencyError,
    TrainingSafetyError,
    load_supervised_dataset,
    run_lora_training,
)
from training.config import LoRAConfigurationError
from training.runner import (
    TrainingReadiness,
    _run_transformers_training,
    inspect_training_readiness,
)

DATASET_PATH = "training/datasets/financial_sft_v1.json"


def _config(**overrides):
    values = {
        "dataset_path": DATASET_PATH,
        "base_model_id": "approved-test-model",
    }
    values.update(overrides)
    return LoRAConfig(**values)


def test_lora_dry_run_validates_dataset_without_importing_optional_modules():
    config = _config()

    with patch("training.runner.importlib.import_module") as import_module:
        result = run_lora_training(config)

    assert result.actual_training_ran is False
    assert result.status.startswith("dry_run")
    import_module.assert_not_called()
    assert result.readiness.dataset_id == "financial-sft-v1"
    assert result.readiness.split_counts == {"train": 2, "validation": 1}


def test_real_run_requires_explicit_confirmation_before_optional_imports():
    config = _config()

    with patch("training.runner.importlib.import_module") as import_module:
        with pytest.raises(TrainingSafetyError, match="confirm_training=True"):
            run_lora_training(config, dry_run=False)

    import_module.assert_not_called()


def test_real_run_reports_missing_optional_dependencies_before_importing():
    config = _config()
    with patch("training.runner.importlib.util.find_spec", return_value=None):
        with patch("training.runner.importlib.import_module") as import_module:
            with pytest.raises(TrainingDependencyError, match="Optional training dependencies"):
                run_lora_training(config, dry_run=False, confirm_training=True)

    import_module.assert_not_called()


def test_readiness_adds_trl_and_bitsandbytes_only_when_requested():
    config = _config(trainer_backend="trl", use_4bit=True)
    with patch("training.runner.importlib.util.find_spec", return_value=object()):
        readiness = inspect_training_readiness(config)

    assert readiness.is_ready_for_execution is True
    assert [dependency.package for dependency in readiness.dependencies] == [
        "torch",
        "transformers",
        "datasets",
        "peft",
        "accelerate",
        "trl",
        "bitsandbytes",
    ]


def test_config_is_strict_and_json_serializable():
    config = LoRAConfig.from_mapping(
        {
            "dataset_path": DATASET_PATH,
            "base_model_id": "approved-test-model",
            "target_modules": ["q_proj", "v_proj"],
        }
    )

    assert config.target_modules == ("q_proj", "v_proj")
    assert config.to_dict()["target_modules"] == ["q_proj", "v_proj"]
    with pytest.raises(LoRAConfigurationError, match="Unsupported"):
        LoRAConfig.from_mapping({"dataset_path": DATASET_PATH, "base_model_id": "model", "unknown": True})


def test_confirmed_run_writes_a_gated_manifest_and_model_card(tmp_path):
    config = _config(
        output_dir=str(tmp_path / "adapter"),
        min_eval_loss_improvement=0.1,
    )
    readiness = TrainingReadiness(
        dataset_id="financial-sft-v1",
        record_count=3,
        split_counts={"train": 2, "validation": 1},
        backend="transformers",
        dependencies=(),
    )
    training_metrics = {
        "train_loss": 0.75,
        "baseline_eval_loss": 1.2,
        "final_eval_loss": 0.8,
    }

    with patch(
        "training.runner.inspect_training_readiness",
        return_value=readiness,
    ):
        with patch(
            "training.runner._run_confirmed_training",
            return_value=(config.output_dir, training_metrics),
        ):
            result = run_lora_training(
                config,
                dry_run=False,
                confirm_training=True,
            )

    assert result.actual_training_ran is True
    assert result.promotion_eligible is True
    assert result.metrics["eval_loss_improvement"] == 0.4

    manifest = json.loads(
        (tmp_path / "adapter" / "adapter_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["promotion_eligible"] is True
    assert manifest["dataset"]["id"] == "financial-sft-v1"
    assert len(manifest["dataset"]["sha256"]) == 64
    assert manifest["evaluation_gate"] == {
        "actual": 0.4,
        "metric": "eval_loss_improvement",
        "minimum": 0.1,
        "passed": True,
    }
    assert (tmp_path / "adapter" / "MODEL_CARD.md").is_file()


@pytest.mark.parametrize(
    "metrics",
    [
        {"train_loss": 0.5},
        {"baseline_eval_loss": 1.0, "final_eval_loss": 1.1},
    ],
)
def test_confirmed_run_refuses_to_promote_without_a_passing_gate(
    tmp_path,
    metrics,
):
    config = _config(output_dir=str(tmp_path / "adapter"))
    readiness = TrainingReadiness(
        dataset_id="financial-sft-v1",
        record_count=3,
        split_counts={"train": 2, "validation": 1},
        backend="transformers",
        dependencies=(),
    )

    with patch(
        "training.runner.inspect_training_readiness",
        return_value=readiness,
    ):
        with patch(
            "training.runner._run_confirmed_training",
            return_value=(config.output_dir, metrics),
        ):
            with pytest.raises(TrainingSafetyError, match="evaluation gate|produce"):
                run_lora_training(
                    config,
                    dry_run=False,
                    confirm_training=True,
                )

    assert not (tmp_path / "adapter" / "adapter_manifest.json").exists()


def test_transformers_runner_measures_validation_before_and_after_training(
    tmp_path,
):
    class FakeDataset:
        def __init__(self, rows):
            self.rows = rows

        @classmethod
        def from_list(cls, rows):
            return cls(rows)

        def map(self, callback, *, batched):
            assert batched is True
            callback({"text": [row["text"] for row in self.rows]})
            return self

    class FakeTokenizer:
        pad_token_id = 0
        eos_token = "<eos>"

        def __call__(self, texts, **_kwargs):
            return {
                "input_ids": [[1, 2] for _text in texts],
                "attention_mask": [[1, 1] for _text in texts],
            }

        def save_pretrained(self, output_dir):
            assert Path(output_dir).is_dir()

    class FakeTrainer:
        def __init__(self, **kwargs):
            assert kwargs["eval_dataset"] is not None
            self.evaluation_count = 0

        def evaluate(self, *, metric_key_prefix):
            self.evaluation_count += 1
            loss = 1.25 if self.evaluation_count == 1 else 0.75
            return {f"{metric_key_prefix}_loss": loss}

        def train(self):
            assert self.evaluation_count == 1
            return SimpleNamespace(metrics={"train_loss": 0.5})

        def save_model(self, output_dir):
            assert Path(output_dir).is_dir()

    class FakeTrainingArguments:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    tokenizer = FakeTokenizer()
    model = SimpleNamespace(config=SimpleNamespace(use_cache=True))
    transformers = SimpleNamespace(
        AutoTokenizer=SimpleNamespace(
            from_pretrained=lambda *_args, **_kwargs: tokenizer
        ),
        AutoModelForCausalLM=SimpleNamespace(
            from_pretrained=lambda *_args, **_kwargs: model
        ),
        TrainingArguments=FakeTrainingArguments,
        Trainer=FakeTrainer,
        default_data_collator=object(),
    )
    peft = SimpleNamespace(
        TaskType=SimpleNamespace(CAUSAL_LM="CAUSAL_LM"),
        LoraConfig=lambda **kwargs: kwargs,
        get_peft_model=lambda supplied_model, _config: supplied_model,
    )
    modules = {
        "transformers": transformers,
        "peft": peft,
        "datasets": SimpleNamespace(Dataset=FakeDataset),
    }
    config = _config(output_dir=str(tmp_path / "fake-adapter"))
    dataset = load_supervised_dataset(DATASET_PATH)

    output_dir, metrics = _run_transformers_training(
        config,
        dataset,
        modules,
    )

    assert output_dir == config.output_dir
    assert model.config.use_cache is False
    assert metrics == {
        "train_loss": 0.5,
        "baseline_eval_loss": 1.25,
        "final_eval_loss": 0.75,
    }
