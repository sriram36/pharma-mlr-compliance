import pytest
from unittest.mock import patch, MagicMock

from core.llm_client import _is_reasoning_model


@pytest.fixture
def mock_llm_client():
    """Create an LLMClient with a mocked underlying OpenAI client.
    
    Settings are loaded from .env at module level by config.py,
    so we construct LLMClient normally and then swap out the internal client.
    """
    from core.llm_client import LLMClient
    client = LLMClient()

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Test content"

    # Provide usage data so the test doesn't crash on usage.prompt_tokens
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 20
    mock_usage.prompt_tokens_details = None
    mock_usage.completion_tokens_details = None
    mock_response.usage = mock_usage

    mock_client.chat.completions.create.return_value = mock_response
    client._client = mock_client
    client._is_reasoning = False  # force non-reasoning for predictable kwargs
    yield client


def test_complete(mock_llm_client):
    result = mock_llm_client.complete(system="System Prompt", user="User Prompt")
    assert result == "Test content"
    assert mock_llm_client.last_usage is not None
    assert mock_llm_client.last_usage["input_tokens"] == 10
    assert mock_llm_client.last_usage["output_tokens"] == 20


class TestIsReasoningModel:
    """Test the _is_reasoning_model detection heuristic."""

    def test_gpt5_mini(self):
        assert _is_reasoning_model("gpt-5-mini") is True

    def test_gpt5(self):
        assert _is_reasoning_model("gpt-5") is True

    def test_o1(self):
        assert _is_reasoning_model("o1") is True

    def test_o3_mini(self):
        assert _is_reasoning_model("o3-mini") is True

    def test_o4_pro(self):
        assert _is_reasoning_model("o4-pro") is True

    def test_gpt4o(self):
        assert _is_reasoning_model("gpt-4o") is False

    def test_gpt4o_mini(self):
        assert _is_reasoning_model("gpt-4o-mini") is False
