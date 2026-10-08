# LoRA training readiness

This package is intentionally separate from the online service. It validates a
versioned, public-safe supervised dataset and produces a dry-run report by
default. A real adapter training run requires both optional dependencies and
an explicit `confirm_training=True` argument.

Example dry run:

```python
from training import LoRAConfig, run_lora_training

config = LoRAConfig(
    dataset_path="training/datasets/financial_sft_v1.json",
    base_model_id="your-approved-base-model",
)
report = run_lora_training(config)
assert report.actual_training_ran is False
```

Install `requirements/training.txt` only in a dedicated training environment.
Use source-reviewed data and verify the base-model license before training.

A confirmed run requires an explicit validation split. The runner evaluates
validation loss before and after training and promotes an adapter only when the
configured `min_eval_loss_improvement` gate passes. A successful output
contains:

- `adapter_manifest.json` with the base model, complete training configuration,
  dataset SHA-256, split counts, metrics, and promotion decision;
- `MODEL_CARD.md` with provenance, gate evidence, and limitations;
- the adapter and tokenizer artifacts produced by the selected trainer.

This loss gate verifies that the run did not regress its validation objective;
it does not prove factual financial quality. Run the versioned RAG and model
benchmarks before deploying an adapter.
