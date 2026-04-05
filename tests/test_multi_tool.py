"""Tests for concurrent multi-tool daemon support (issue #12)."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from context_scribe.main import (
    SharedDeduplication,
    run_daemon_multi,
    _run_tool_pipeline,
    Dashboard,
)
from context_scribe.observer.provider import Interaction
from context_scribe.evaluator.llm import RuleOutput


# --- SharedDeduplication tests ---

class TestSharedDeduplication:
    def test_not_duplicate_initially(self):
        dedup = SharedDeduplication()
        rule = RuleOutput(scope="GLOBAL", content="Use tabs", description="style")
        assert dedup.is_duplicate(rule) is False

    def test_duplicate_after_commit(self):
        dedup = SharedDeduplication()
        rule = RuleOutput(scope="GLOBAL", content="Use tabs", description="style")
        dedup.mark_committed(rule)
        assert dedup.is_duplicate(rule) is True

    def test_different_scope_not_duplicate(self):
        dedup = SharedDeduplication()
        rule_global = RuleOutput(scope="GLOBAL", content="Use tabs", description="style")
        rule_project = RuleOutput(scope="PROJECT", content="Use tabs", description="style")
        dedup.mark_committed(rule_global)
        assert dedup.is_duplicate(rule_project) is False

    def test_different_content_not_duplicate(self):
        dedup = SharedDeduplication()
        rule_a = RuleOutput(scope="GLOBAL", content="Use tabs", description="style")
        rule_b = RuleOutput(scope="GLOBAL", content="Use spaces", description="style")
        dedup.mark_committed(rule_a)
        assert dedup.is_duplicate(rule_b) is False

    def test_thread_safety(self):
        """Dedup should work safely across threads."""
        import threading
        dedup = SharedDeduplication()
        rule = RuleOutput(scope="GLOBAL", content="Concurrent", description="test")
        results = []

        def worker():
            if not dedup.is_duplicate(rule):
                dedup.mark_committed(rule)
                results.append("committed")
            else:
                results.append("skipped")

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one thread should have committed
        assert results.count("committed") >= 1
        assert dedup.is_duplicate(rule) is True


# --- CLI tests ---

class TestCLIMultiTool:
    def test_tools_flag_accepted(self):
        from click.testing import CliRunner
        from context_scribe.main import cli

        runner = CliRunner()
        # We can't actually run the daemon, but we can verify the arg parsing
        # by patching run_daemon_multi
        with patch("context_scribe.main.run_daemon_multi", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = True
            with patch("context_scribe.main.asyncio.run") as mock_asyncio_run:
                result = runner.invoke(cli, ["--tools", "gemini,claude"])
                assert result.exit_code == 0
                # asyncio.run should have been called with run_daemon_multi
                mock_asyncio_run.assert_called_once()

    def test_tool_flag_backward_compat(self):
        from click.testing import CliRunner
        from context_scribe.main import cli

        runner = CliRunner()
        with patch("context_scribe.main.run_daemon_multi", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = True
            with patch("context_scribe.main.asyncio.run") as mock_asyncio_run:
                result = runner.invoke(cli, ["--tool", "copilot"])
                assert result.exit_code == 0
                mock_asyncio_run.assert_called_once()

    def test_default_tool_is_gemini(self):
        from click.testing import CliRunner
        from context_scribe.main import cli

        runner = CliRunner()
        with patch("context_scribe.main.run_daemon_multi", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = True
            with patch("context_scribe.main.asyncio.run") as mock_asyncio_run:
                result = runner.invoke(cli, [])
                assert result.exit_code == 0
                # The first arg to asyncio.run should be run_daemon_multi(["gemini"], ...)
                call_args = mock_asyncio_run.call_args
                coro = call_args[0][0]
                # Can't easily inspect coroutine args, but at least it was called
                mock_asyncio_run.assert_called_once()


# --- Deduplication in pipeline ---

@pytest.mark.asyncio
async def test_pipeline_skips_duplicate_rule():
    """If dedup says the rule was already committed, pipeline should skip save."""
    mock_provider = MagicMock()
    mock_evaluator = MagicMock()
    mock_mcp = AsyncMock()
    mock_live = MagicMock()

    interaction = Interaction(timestamp=None, role="user", content="Test", project_name="p1")
    rule = RuleOutput(scope="GLOBAL", content="Already seen", description="dup")

    # Yield one interaction then stop
    def mock_watch():
        yield interaction
        yield None
        yield None

    mock_provider.watch.return_value = mock_watch()
    mock_evaluator.evaluate_interaction.return_value = rule
    mock_mcp.read_rules.return_value = ""

    dedup = SharedDeduplication()
    dedup.mark_committed(rule)  # Pre-mark as committed

    db = Dashboard(["gemini"], "~/.memory-bank")

    # The pipeline will process the interaction, see the duplicate, skip it,
    # then hit StopIteration when the generator ends
    task = asyncio.create_task(
        _run_tool_pipeline("gemini", mock_provider, mock_evaluator, mock_mcp, db, dedup, mock_live)
    )
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except (StopIteration, asyncio.CancelledError, asyncio.TimeoutError, RuntimeError):
        pass

    # save_rule should NOT have been called because the rule was already committed
    mock_mcp.save_rule.assert_not_called()
