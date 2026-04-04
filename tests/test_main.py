import click
import pytest
from unittest.mock import patch, MagicMock
from context_scribe.main import (
    bootstrap_global_config, 
    bootstrap_copilot_config, 
    bootstrap_claude_config, 
    Dashboard,
    _detect_evaluator
)

def test_detect_evaluator_prefers_tool():
    """Test that it returns the preferred tool if available."""
    with patch("shutil.which") as mock_which:
        mock_which.side_effect = lambda x: True
        assert _detect_evaluator("gemini-cli") == "gemini"
        assert _detect_evaluator("claude") == "claude"
        assert _detect_evaluator("copilot") == "copilot"

def test_detect_evaluator_fallback_if_preferred_missing():
    """Test that it falls back to others if preferred tool is missing."""
    with patch("shutil.which") as mock_which:
        # Preferred tool 'gemini' is missing, but 'claude' exists
        mock_which.side_effect = lambda x: x == "claude"
        assert _detect_evaluator("gemini-cli") == "claude"

def test_detect_evaluator_fails_if_none_found():
    """Test that it raises ClickException if no tools are found."""
    with patch("shutil.which") as mock_which:
        mock_which.return_value = None
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(click.ClickException) as excinfo:
                _detect_evaluator()
            assert "No supported evaluator found" in str(excinfo.value)

def test_bootstrap_global_config_creates_file(tmp_path):
    # Mock home directory to our temp path
    with patch("os.path.expanduser") as mock_expand:
        mock_expand.side_effect = lambda x: x.replace("~", str(tmp_path))
        bootstrap_global_config()
        gemini_md = tmp_path / ".gemini" / "GEMINI.md"
        assert gemini_md.exists()
        assert "Memory Bank Integration" in gemini_md.read_text()

def test_bootstrap_global_config_updates_if_outdated(tmp_path):
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir(parents=True)
    gemini_md = gemini_dir / "GEMINI.md"
    gemini_md.write_text("Old rule without precedence")
    
    with patch("os.path.expanduser") as mock_expand:
        mock_expand.side_effect = lambda x: x.replace("~", str(tmp_path))
        bootstrap_global_config()
        # It should append the new rule if "Rule Precedence:" is missing
        assert "Rule Precedence:" in gemini_md.read_text()

def test_bootstrap_copilot_config_creates_file(tmp_path):
    with patch("os.path.expanduser") as mock_expand:
        mock_expand.side_effect = lambda x: x.replace("~", str(tmp_path))
        bootstrap_copilot_config()
        instructions_md = tmp_path / ".config" / "github-copilot" / "instructions.md"
        assert instructions_md.exists()
        assert "Memory Bank Integration" in instructions_md.read_text()

def test_bootstrap_claude_config_creates_file(tmp_path):
    with patch("os.path.expanduser") as mock_expand:
        mock_expand.side_effect = lambda x: x.replace("~", str(tmp_path))
        bootstrap_claude_config()
        claude_md = tmp_path / ".claude" / "CLAUDE.md"
        assert claude_md.exists()
        assert "Memory Bank Integration" in claude_md.read_text()

def test_bootstrap_claude_config_updates_if_outdated(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    claude_md = claude_dir / "CLAUDE.md"
    claude_md.write_text("Old rule without precedence")

    with patch("os.path.expanduser") as mock_expand:
        mock_expand.side_effect = lambda x: x.replace("~", str(tmp_path))
        bootstrap_claude_config()
        assert "Rule Precedence:" in claude_md.read_text()

def test_bootstrap_claude_config_skips_if_up_to_date(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    claude_md = claude_dir / "CLAUDE.md"
    claude_md.write_text("Existing content with Rule Precedence: already present")

    with patch("os.path.expanduser") as mock_expand:
        mock_expand.side_effect = lambda x: x.replace("~", str(tmp_path))
        bootstrap_claude_config()
        content = claude_md.read_text()
        assert content.count("Rule Precedence:") == 1


def test_dashboard_generate_layout():
    db = Dashboard("gemini-cli", "~/.memory-bank")
    db.status = "✅ SUCCESS"
    layout = db.generate_layout()
    assert layout is not None
    # Check if history is displayed
    db.add_history("test.md", "Update text")
    layout = db.generate_layout()
    # Check if some component contains the text
    assert layout["history"] is not None
