from __future__ import annotations

from dataclasses import dataclass

from .schema import Usage


@dataclass(frozen=True)
class Price:
    input_per_million: float
    output_per_million: float
    basis: str


PRICES: dict[str, Price] = {
    "jev-latest": Price(
        0.042,
        0,
        "Published TypeSafe direct API rate; output tokens are free.",
    ),
    "jev-1.13.0": Price(
        0.042,
        0,
        "Published TypeSafe direct API rate; output tokens are free.",
    ),
    "opencode-go/glm-5.3-flash": Price(
        0.15,
        0.50,
        "Reference token-equivalent estimate using published GLM 5.3 Flash rates; OpenCode Go is subscription-billed, so this is not the marginal invoice charge.",
    ),
}


def estimate_cost(model: str, usage: Usage) -> float | None:
    if model.startswith("laya:"):
        return 0.0
    price = PRICES.get(model)
    if price is None:
        return None
    return (
        usage.input_tokens * price.input_per_million
        + usage.output_tokens * price.output_per_million
    ) / 1_000_000


def with_estimated_cost(model: str, usage: Usage) -> Usage:
    if usage.cost is not None:
        return usage
    return usage.model_copy(update={"cost": estimate_cost(model, usage)})


def cost_basis(model: str) -> str:
    if model.startswith("laya:"):
        return "Self-hosted open weights; provider cost is $0, excluding local hardware and electricity."
    price = PRICES.get(model)
    return price.basis if price else "No pricing basis is configured for this resolved model."
