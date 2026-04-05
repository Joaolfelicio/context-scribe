import pytest
import os
from unittest.mock import AsyncMock, patch, MagicMock
from context_scribe.main import run_daemon, run_daemon_multi

@pytest.mark.asyncio
async def test_run_daemon_mcp_connection_failure():
    mock_mcp = AsyncMock()
    mock_mcp.connect.side_effect = Exception("Connection failed")

    # Create a mock for GeminiProvider and its watch method
    mock_provider = MagicMock()
    mock_provider.watch.return_value = iter([])

    with patch("context_scribe.main.MemoryBankClient", return_value=mock_mcp):
        with patch("context_scribe.main.create_provider", return_value=mock_provider):
            with patch("context_scribe.main.create_evaluator"):
                with patch("context_scribe.main.bootstrap_tool"):
                    # Mock the Dashboard CLASS to prevent layout generation
                    with patch("context_scribe.main.Dashboard") as mock_db_class:
                        # Ensure generate_layout returns something simple
                        mock_db_class.return_value.generate_layout.return_value = MagicMock()

                        with patch("os._exit", side_effect=SystemExit(1)) as mock_exit:
                            with patch("context_scribe.main.Live") as mock_live:
                                # Make the context manager work
                                mock_live.return_value.__enter__.return_value = MagicMock()
                                with pytest.raises(SystemExit):
                                    await run_daemon("gemini", "~/.memory-bank")
                                mock_exit.assert_called_once_with(1)

def test_cli_rejects_unsupported_tool():
    """click.Choice validation rejects unsupported tool values."""
    from click.testing import CliRunner
    from context_scribe.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--tool", "unsupported"])
    assert result.exit_code != 0
    assert "Invalid value" in result.output or "invalid choice" in result.output.lower()

def test_cli_rejects_invalid_tools_list():
    """--tools with invalid tool name is rejected."""
    from click.testing import CliRunner
    from context_scribe.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--tools", "gemini,foobar"])
    assert result.exit_code != 0

def test_cli_rejects_tool_and_tools_together():
    """Cannot use --tool and --tools at the same time."""
    from click.testing import CliRunner
    from context_scribe.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--tool", "gemini", "--tools", "claude"])
    assert result.exit_code != 0

@pytest.mark.asyncio
async def test_run_daemon_multi_invalid_tool():
    """run_daemon_multi returns False for unknown tool."""
    result = await run_daemon_multi(["nonexistent"], "~/.memory-bank")
    assert result is False
