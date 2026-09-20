from __future__ import annotations

import os
from uuid import uuid4

import dspy


def create_lm(
    model: str,
    *,
    temperature: float = 0,
    max_tokens: int = 5_000,
) -> dspy.LM:
    if model.startswith("opencode-go/"):
        api_key = os.getenv("OPENCODE_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENCODE_API_KEY or OPENAI_API_KEY is required for opencode-go")
        api_base = (
            os.getenv("OPENCODE_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://opencode.ai/zen/go/v1"
        )
        return dspy.LM(
            f"openai/{model.removeprefix('opencode-go/')}",
            temperature=temperature,
            max_tokens=max_tokens,
            cache=False,
            num_retries=2,
            api_key=api_key,
            api_base=api_base,
            extra_headers={"x-opencode-session": str(uuid4())},
        )
    return dspy.LM(
        model,
        temperature=temperature,
        max_tokens=max_tokens,
        cache=False,
        num_retries=2,
    )
