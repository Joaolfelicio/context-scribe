"""Tests for concurrent multi-tool daemon support."""
import asyncio
import sys
from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture(autouse=True)
def mock_heavy_deps():
    """Mock heavy imports so we can import main without mcp/rich."""
    mocks = {}
    for mod in ["mcp", "mcp.client", "mcp.client.stdio",
                 "rich", "rich.console", "rich.live", "rich.panel",
                 "rich.text", "rich.layout", "rich.table", "rich.spinner"]:
        if mod not in sys.modules or not hasattr(sys.modules.get(mod), '__file__'):
            mocks[mod] = MagicMock()
    with patch.dict(sys.modules, mocks):
        # Clear cached imports so they re-resolve with mocks
        for key in list(sys.modules.keys()):
            if key.startswith("context_scribe.main") or key.startswith("context_scribe.bridge"):
                del sys.modules[key]
        yield


def test_tool_registry_populated():
    from context_scribe.main import TOOL_REGISTRY
    assert "gemini-cli" in TOOL_REGISTRY
    assert "copilot" in TOOL_REGISTRY
    assert "claude" in TOOL_REGISTRY


def test_create_providers_single():
    from context_scribe.main import _create_providers
    with patch("context_scribe.main.bootstrap_global_config"):
        with patch("context_scribe.main.GeminiCliProvider") as mock_cls:
            mock_cls.return_value = MagicMock()
            providers = _create_providers(["gemini-cli"])
    assert len(providers) == 1
    assert providers[0][0] == "gemini-cli"


def test_create_providers_multiple():
    from context_scribe.main import _create_providers
    with patch("context_scribe.main.bootstrap_global_config"):
        with patch("context_scribe.main.bootstrap_claude_config"):
            with patch("context_scribe.main.GeminiCliProvider", return_value=MagicMock()):
                with patch("context_scribe.main.ClaudeProvider", return_value=MagicMock()):
                    providers = _create_providers(["gemini-cli", "claude"])
    assert len(providers) == 2
    names = [p[0] for p in providers]
    assert "gemini-cli" in names
    assert "claude" in names


def test_create_providers_unknown_raises():
    from context_scribe.main import _create_providers
    with pytest.raises(ValueError, match="Unknown tool"):
        _create_providers(["nonexistent"])


def test_create_providers_calls_bootstrap():
    from context_scribe.main import _create_providers, TOOL_REGISTRY
    mock_boot = MagicMock()
    original = TOOL_REGISTRY["gemini-cli"]
    TOOL_REGISTRY["gemini-cli"] = (original[0], mock_boot)
    try:
        with patch("context_scribe.main.GeminiCliProvider", return_value=MagicMock()):
            _create_providers(["gemini-cli"])
        mock_boot.assert_called_once()
    finally:
        TOOL_REGISTRY["gemini-cli"] = original


def test_create_providers_all_three():
    from context_scribe.main import _create_providers
    with patch("context_scribe.main.bootstrap_global_config"):
        with patch("context_scribe.main.bootstrap_copilot_config"):
            with patch("context_scribe.main.bootstrap_claude_config"):
                with patch("context_scribe.main.GeminiCliProvider", return_value=MagicMock()):
                    with patch("context_scribe.main.CopilotProvider", return_value=MagicMock()):
                        with patch("context_scribe.main.ClaudeProvider", return_value=MagicMock()):
                            providers = _create_providers(["gemini-cli", "copilot", "claude"])
    assert len(providers) == 3


# --- CLI tests for --tools flag ---

def test_cli_tools_deduplication():
    """--tools with duplicate entries should deduplicate preserving order."""
    from click.testing import CliRunner
    from context_scribe.main import cli

    runner = CliRunner()
    captured_tools = {}

    original_run_daemon = None

    async def fake_run_daemon(tool, bank_path, debug=False, evaluator_name="auto", tools=None):
        captured_tools["tools"] = tools
        return True

    with patch("context_scribe.main.run_daemon", side_effect=fake_run_daemon) as mock_rd:
        loop = asyncio.new_event_loop()
        with patch("asyncio.run", side_effect=lambda coro: loop.run_until_complete(coro)):
            result = runner.invoke(cli, ["--tools", "gemini-cli,gemini-cli,claude"])

    assert result.exit_code == 0
    assert captured_tools["tools"] == ["gemini-cli", "claude"]


def test_cli_tools_invalid_tool():
    """--tools with an unknown tool name should fail with a clear error."""
    from click.testing import CliRunner
    from context_scribe.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--tools", "gemini-cli,nonexistent"])
    assert result.exit_code != 0
    assert "Unknown tool(s): nonexistent" in result.output


def test_cli_tools_empty_string():
    """--tools with an empty string should fail."""
    from click.testing import CliRunner
    from context_scribe.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--tools", ""])
    assert result.exit_code != 0
    assert "--tools requires at least one tool name" in result.output


def test_cli_tools_whitespace_only():
    """--tools with only whitespace/commas should fail."""
    from click.testing import CliRunner
    from context_scribe.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--tools", " , , "])
    assert result.exit_code != 0
    assert "--tools requires at least one tool name" in result.output
