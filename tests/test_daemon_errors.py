import pytest
import os
from unittest.mock import AsyncMock, patch, MagicMock
from context_scribe.main import run_daemon

@pytest.mark.asyncio
async def test_run_daemon_mcp_connection_failure():
    mock_mcp = AsyncMock()
    mock_mcp.connect.side_effect = Exception("Connection failed")
    
    # Create a mock for GeminiProvider and its watch method
    mock_provider = MagicMock()
    mock_provider.watch.return_value = iter([])
    
    with patch("context_scribe.main.MemoryBankClient", return_value=mock_mcp):
        with patch("context_scribe.main.GeminiProvider", return_value=mock_provider):
            with patch("context_scribe.main.Evaluator"):
                with patch("context_scribe.main.bootstrap_global_config"):
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

@pytest.mark.asyncio
async def test_run_daemon_unsupported_tool():
    result = await run_daemon("unsupported", "~/.memory-bank")
    assert result is False
