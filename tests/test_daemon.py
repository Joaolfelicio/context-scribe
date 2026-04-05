import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from context_scribe.main import run_daemon, run_daemon_multi
from context_scribe.observer.provider import Interaction
from context_scribe.evaluator.llm import RuleOutput

@pytest.mark.asyncio
async def test_run_daemon_loop_one_iteration():
    # Mock dependencies
    mock_provider = MagicMock()
    mock_evaluator = MagicMock()
    mock_mcp = AsyncMock()

    # Setup interaction
    mock_interaction = Interaction(
        timestamp=None,
        role="user",
        content="New Rule",
        project_name="p1"
    )

    # Mock watch iterator: yield one interaction then None then raise KeyboardInterrupt
    def mock_watch():
        yield mock_interaction
        yield None
        raise KeyboardInterrupt()

    mock_provider.watch.return_value = mock_watch()

    # Correct RuleOutput with description
    mock_rule_output = RuleOutput(scope="GLOBAL", content="Extracted Rule", description="Added new rule")
    mock_evaluator.evaluate_interaction.return_value = mock_rule_output

    # Mock read_rules
    mock_mcp.read_rules.return_value = ""

    # Track interaction processing to break loop
    processed_interaction = False
    async def side_effect(*args, **kwargs):
        nonlocal processed_interaction
        processed_interaction = True
        return MagicMock()
    mock_mcp.save_rule.side_effect = side_effect

    with patch("context_scribe.main.create_provider", return_value=mock_provider):
        with patch("context_scribe.main.create_evaluator", return_value=mock_evaluator):
            with patch("context_scribe.main.MemoryBankClient", return_value=mock_mcp):
                with patch("context_scribe.main.bootstrap_tool"):
                    # Mock Live to avoid rich rendering logic completely
                    with patch("context_scribe.main.Live") as mock_live:
                        with patch("os._exit") as mock_exit:
                            # Make the context manager work
                            mock_live.return_value.__enter__.return_value = MagicMock()

                            # Start daemon and wait for it to process the mocked interaction
                            daemon_task = asyncio.create_task(run_daemon("gemini", "~/.memory-bank"))

                            # Wait until save_rule is called (meaning interaction processed)
                            for _ in range(50):
                                if processed_interaction:
                                    break
                                await asyncio.sleep(0.1)

                            daemon_task.cancel()
                            try:
                                await daemon_task
                            except asyncio.CancelledError:
                                pass

                        # Verify calls
                        mock_mcp.connect.assert_called_once()
                        mock_mcp.read_rules.assert_called()
                        mock_evaluator.evaluate_interaction.assert_called()
                        mock_mcp.save_rule.assert_called_once_with("Extracted Rule", "global", "global_rules.md")


@pytest.mark.asyncio
async def test_run_daemon_multi_two_tools():
    """Test that run_daemon_multi creates pipelines for two tools concurrently."""
    mock_provider_gemini = MagicMock()
    mock_provider_claude = MagicMock()
    mock_evaluator = MagicMock()
    mock_mcp = AsyncMock()

    interaction = Interaction(
        timestamp=None, role="user", content="Test", project_name="p1"
    )

    def mock_watch_gemini():
        yield interaction
        while True:
            yield None

    def mock_watch_claude():
        yield interaction
        while True:
            yield None

    mock_provider_gemini.watch.return_value = mock_watch_gemini()
    mock_provider_claude.watch.return_value = mock_watch_claude()

    rule = RuleOutput(scope="GLOBAL", content="Rule A", description="rule a")
    mock_evaluator.evaluate_interaction.return_value = rule
    mock_mcp.read_rules.return_value = ""

    call_count = 0

    async def save_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return MagicMock()

    mock_mcp.save_rule.side_effect = save_side_effect

    def mock_create_provider(tool):
        if tool == "gemini":
            return mock_provider_gemini
        return mock_provider_claude

    with patch("context_scribe.main.create_provider", side_effect=mock_create_provider):
        with patch("context_scribe.main.create_evaluator", return_value=mock_evaluator):
            with patch("context_scribe.main.MemoryBankClient", return_value=mock_mcp):
                with patch("context_scribe.main.bootstrap_tool"):
                    with patch("context_scribe.main.Live") as mock_live:
                        mock_live.return_value.__enter__.return_value = MagicMock()
                        task = asyncio.create_task(
                            run_daemon_multi(["gemini", "claude"], "~/.memory-bank")
                        )
                        # Wait for at least one save from each tool
                        for _ in range(50):
                            if call_count >= 1:
                                break
                            await asyncio.sleep(0.1)

                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                        # At least one save should have occurred
                        assert mock_mcp.save_rule.called
                        # Both providers should have had watch() called
                        mock_provider_gemini.watch.assert_called_once()
                        mock_provider_claude.watch.assert_called_once()
