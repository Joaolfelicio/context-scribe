import pytest
import asyncio
from unittest.mock import MagicMock, patch
from context_scribe.main import run_daemon

@pytest.mark.asyncio
@pytest.mark.parametrize("tool, provider_class, evaluator_class, bootstrap_func, evaluator_name", [
    ("gemini-cli", "GeminiCliProvider", "GeminiCliEvaluator", "bootstrap_global_config", "gemini"),
    ("copilot", "CopilotProvider", "CopilotEvaluator", "bootstrap_copilot_config", "copilot"),
    ("claude", "ClaudeProvider", "ClaudeEvaluator", "bootstrap_claude_config", "claude"),
])
async def test_run_daemon_tools(tool, provider_class, evaluator_class, bootstrap_func, evaluator_name, daemon_mocks):
    """Test the daemon run loop for all supported tools."""
    
    with patch(f"context_scribe.main.{provider_class}", return_value=daemon_mocks.provider):
        with patch(f"context_scribe.main.{evaluator_class}", return_value=daemon_mocks.evaluator):
            with patch("context_scribe.main.MemoryBankClient", return_value=daemon_mocks.mcp):
                with patch(f"context_scribe.main.{bootstrap_func}"):
                    # Mock Live to avoid rich rendering logic completely
                    with patch("context_scribe.main.Live") as mock_live:
                        with patch("os._exit") as mock_exit:
                            # Make the context manager work
                            mock_live.return_value.__enter__.return_value = MagicMock()

                            # Start daemon and wait for it to process the mocked interaction
                            daemon_task = asyncio.create_task(run_daemon(tool, "~/.memory-bank", evaluator_name=evaluator_name))

                            # Wait until save_rule is called (meaning interaction processed)
                            for _ in range(50):
                                if daemon_mocks.processed_interaction:
                                    break
                                await asyncio.sleep(0.1)

                            daemon_task.cancel()
                            try:
                                await daemon_task
                            except asyncio.CancelledError:
                                pass

                        # Verify calls
                        daemon_mocks.mcp.connect.assert_called_once()
                        daemon_mocks.mcp.read_rules.assert_called()
                        daemon_mocks.evaluator.evaluate_interaction.assert_called()
                        daemon_mocks.mcp.save_rule.assert_called_once_with("Extracted Rule", "global", "global_rules.md")
