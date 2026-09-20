from __future__ import annotations

import json
from importlib import import_module
from typing import Any

from ..normalize import normalize_jev_categorical_response
from ..rubric import build_categorical_questions
from ..schema import ReviewState, Scorecard


class LayaEvaluator:
    def __init__(
        self,
        model: str,
        *,
        subfolder: str | None = None,
        device: str | None = None,
        revision: str | None = None,
        agent: Any | None = None,
    ) -> None:
        if agent is None:
            try:
                laya = import_module("laya")
            except ImportError as error:
                raise RuntimeError(
                    "Laya evaluation requires `uv run --with laya==0.3.4 jev-dspy ...`"
                ) from error
            source = model
            if revision:
                snapshot_download = import_module("huggingface_hub").snapshot_download
                source = snapshot_download(model, revision=revision)
            agent = laya.load(source, subfolder=subfolder, device=device)
        self.agent = agent
        self.model = model
        self.subfolder = subfolder
        self.revision = revision
        checkpoint = f"{model}/{subfolder}" if subfolder else model
        self.id = f"laya:{checkpoint}"
        self.last_diagnostics: dict[str, Any] | None = None

    def evaluate(self, state: ReviewState) -> Scorecard:
        questions = build_categorical_questions()
        raw = self.agent.predict(state.model_dump(), questions)
        if not isinstance(raw, dict):
            raise ValueError("Laya returned an invalid response")
        raw = dict(raw)
        raw["model"] = self.id
        self.last_diagnostics = self._diagnostics(state, questions)
        return normalize_jev_categorical_response(raw)

    def _diagnostics(
        self, state: ReviewState, questions: dict[str, dict[str, object]]
    ) -> dict[str, Any]:
        try:
            build_sequence = import_module("laya.common").build_sequence

            serialized = json.dumps(state.model_dump(), ensure_ascii=False)
            state_tokens = len(self.agent.tok(serialized, add_special_tokens=False)["input_ids"])
            retained: list[int] = []
            for definition in questions.values():
                internal = self.agent._to_internal(definition)
                sequence, _ = build_sequence(
                    self.agent.tok,
                    state.model_dump(),
                    internal,
                    self.agent.cfg["max_len"],
                    self.agent.cfg["head_max_len"],
                )
                empty, _ = build_sequence(
                    self.agent.tok,
                    {},
                    internal,
                    self.agent.cfg["max_len"],
                    self.agent.cfg["head_max_len"],
                )
                room = self.agent.cfg["max_len"] - len(empty)
                retained.append(min(state_tokens, room, len(sequence)))
            return {
                "device": str(self.agent.device),
                "revision": self.revision,
                "maxLength": self.agent.cfg["max_len"],
                "headMaxLength": self.agent.cfg["head_max_len"],
                "stateTokens": state_tokens,
                "minimumStateTokensRetained": min(retained),
                "maximumStateTokensRetained": max(retained),
                "minimumStateRetentionRatio": min(retained) / state_tokens,
                "maximumStateRetentionRatio": max(retained) / state_tokens,
            }
        except (AttributeError, ImportError, KeyError, TypeError, ValueError):
            return {}
