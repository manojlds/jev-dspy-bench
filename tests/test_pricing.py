import pytest

from jev_dspy_bench.pricing import cost_basis, estimate_cost
from jev_dspy_bench.schema import Usage


def test_estimates_direct_jev_cost_from_published_rate() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=500_000, total_tokens=1_500_000)
    assert estimate_cost("jev-1.13.0", usage) == pytest.approx(0.042)


def test_labels_go_cost_as_reference_not_invoice_charge() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000, total_tokens=2_000_000)
    assert estimate_cost("opencode-go/glm-5.3-flash", usage) == pytest.approx(0.65)
    assert "subscription-billed" in cost_basis("opencode-go/glm-5.3-flash")


def test_labels_laya_as_self_hosted() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=0, total_tokens=1_000_000)
    assert estimate_cost("laya:convaiinnovations/laya", usage) == 0
    assert "Self-hosted open weights" in cost_basis("laya:convaiinnovations/laya")
