"""Opt-in supervised fine-tuning utilities.

Nothing in this package is imported by the online application.  Training is
an explicit, offline workflow so production requests cannot accidentally load
large model or GPU dependencies.
"""

from training.config import LoRAConfig
from training.dataset import (
    SUPERVISED_DATASET_SCHEMA_VERSION,
    SupervisedDataset,
    TrainingDatasetValidationError,
    load_supervised_dataset,
)
from training.runner import (
    TrainingDependencyError,
    TrainingRunResult,
    TrainingSafetyError,
    inspect_training_readiness,
    run_lora_training,
)

__all__ = [
    "LoRAConfig",
    "SUPERVISED_DATASET_SCHEMA_VERSION",
    "SupervisedDataset",
    "TrainingDatasetValidationError",
    "TrainingDependencyError",
    "TrainingRunResult",
    "TrainingSafetyError",
    "inspect_training_readiness",
    "load_supervised_dataset",
    "run_lora_training",
]
