"""Unit tests for model_adapter (mocked subprocess + openai)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make model_adapter importable without relying on package discovery.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import model_adapter as ma  # noqa: E402


def test_route_sonnet_uses_claude_cli():
    fake_proc = MagicMock(stdout=json.dumps({
        "result": "Smith v. Jones, 1 U.S. 1 (1900)",
        "total_cost_usd": 0.05,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }), stderr="", returncode=0)
    with patch.object(ma.subprocess, "run", return_value=fake_proc) as mock_run:
        result = ma.call_model("test prompt", "sonnet")
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "claude"
    assert "--model" in cmd and "sonnet" in cmd
    assert result["response"] == "Smith v. Jones, 1 U.S. 1 (1900)"
    assert result["cost_usd"] == 0.05
    assert result["input_tokens"] == 100


def test_route_opus_uses_claude_cli_with_opus():
    fake_proc = MagicMock(stdout=json.dumps({
        "result": "UNKNOWN", "total_cost_usd": 0.10, "usage": {}
    }), stderr="", returncode=0)
    with patch.object(ma.subprocess, "run", return_value=fake_proc) as mock_run:
        ma.call_model("p", "opus")
    cmd = mock_run.call_args[0][0]
    assert "opus" in cmd


def test_route_gpt5_uses_openai_without_temperature():
    """GPT-5 rejects temperature=0; adapter must omit temperature."""
    fake_completion = MagicMock()
    fake_completion.choices = [
        MagicMock(message=MagicMock(content="Doe v. Roe, 2 F.2d 3 (1950)"))
    ]
    fake_completion.usage = MagicMock(prompt_tokens=80, completion_tokens=15)
    fake_completion.model = "gpt-5-2025-08-07"
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_completion
    with patch.object(ma, "_openai_client", return_value=fake_client):
        result = ma.call_model("p", "gpt-5")
    create_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert "temperature" not in create_kwargs, \
        "GPT-5 must not be called with temperature (only default 1 is allowed)"
    assert create_kwargs.get("max_completion_tokens", 0) >= 2000, \
        "GPT-5 needs >=2000 token budget for reasoning + output"
    assert result["response"] == "Doe v. Roe, 2 F.2d 3 (1950)"
    assert result["input_tokens"] == 80
    assert result["output_tokens"] == 15
    assert result["model_id"] == "gpt-5-2025-08-07"


def test_unknown_model_raises():
    with pytest.raises(ValueError, match="unknown model"):
        ma.call_model("p", "bogus-model")


def test_claude_timeout_returns_empty_response():
    with patch.object(ma.subprocess, "run",
                      side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=60)):
        result = ma.call_model("p", "sonnet", timeout_s=60)
    assert result["response"] == ""
    assert result["stderr"] == "TIMEOUT"


def test_gpt5_error_returns_stderr_with_message():
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = Exception("rate limit")
    with patch.object(ma, "_openai_client", return_value=fake_client):
        result = ma.call_model("p", "gpt-5")
    assert result["response"] == ""
    assert "OPENAI_ERROR" in result["stderr"]
    assert "rate limit" in result["stderr"]
