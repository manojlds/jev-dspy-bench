from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvaluatorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["jev", "direct", "dspy"]
    model: str | None = None
    program: str | None = None
    batchSize: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def model_required(self) -> EvaluatorConfig:
        if self.kind != "jev" and not self.model:
            raise ValueError(f"model is required for {self.kind}")
        return self


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    split: str
    partition: Literal["train", "dev", "test"] = "test"
    repeat: int = Field(default=1, ge=1)
    live: bool = False
    output: str = "artifacts/runs"
    evaluators: list[EvaluatorConfig]


def load_config(path: Path) -> ExperimentConfig:
    return ExperimentConfig.model_validate(yaml.safe_load(path.read_text()))
