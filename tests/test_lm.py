from typing import Any

import pytest

from jev_dspy_bench import lm as lm_module


def test_maps_opencode_go_to_openai_compatible_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_lm(model: str, **options: object) -> object:
        captured["model"] = model
        captured.update(options)
        return object()

    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr(lm_module.dspy, "LM", fake_lm)

    lm_module.create_lm("opencode-go/deepseek-v4.1-flash")

    assert captured["model"] == "openai/deepseek-v4.1-flash"
    assert captured["api_base"] == "https://example.test/v1"
    assert captured["api_key"] == "secret"
    headers = captured["extra_headers"]
    assert isinstance(headers, dict)
    assert headers["x-opencode-session"]


def test_opencode_go_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API_KEY"):
        lm_module.create_lm("opencode-go/deepseek-v4.1-flash")
