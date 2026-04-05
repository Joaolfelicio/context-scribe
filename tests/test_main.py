from unittest.mock import patch
from context_scribe.main import (
    bootstrap_global_config, bootstrap_copilot_config, bootstrap_claude_config,
    Dashboard, parse_tools, create_provider, create_evaluator,
)
import click
import pytest

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


# --- Dashboard tests (single tool backward compat) ---

def test_dashboard_generate_layout():
    db = Dashboard(["gemini"], "~/.memory-bank")
    db.status = "✅ SUCCESS"
    layout = db.generate_layout()
    assert layout is not None
    db.add_history("test.md", "Update text")
    layout = db.generate_layout()
    assert layout["history"] is not None

def test_dashboard_single_tool_compat():
    db = Dashboard(["gemini"], "~/.memory-bank")
    assert db.tool == "gemini"
    db.status = "running"
    assert db.tool_status["gemini"] == "running"


# --- Dashboard multi-tool tests ---

def test_dashboard_multi_tool_status():
    db = Dashboard(["gemini", "claude"], "~/.memory-bank")
    db.set_tool_status("gemini", "🔍 Watching")
    db.set_tool_status("claude", "🧠 Thinking")
    assert db.tool_status["gemini"] == "🔍 Watching"
    assert db.tool_status["claude"] == "🧠 Thinking"
    layout = db.generate_layout()
    assert layout is not None

def test_dashboard_multi_tool_history():
    db = Dashboard(["gemini", "claude"], "~/.memory-bank")
    db.add_history("global/global_rules.md", "Added rule", tool="gemini")
    db.add_history("proj/rules.md", "Project rule", tool="claude")
    assert db.update_count == 2
    assert len(db.history) == 2
    # Most recent first
    assert db.history[0][1] == "claude"
    assert db.history[1][1] == "gemini"


# --- parse_tools tests ---

def test_parse_tools_single():
    assert parse_tools("gemini") == ["gemini"]

def test_parse_tools_multiple():
    assert parse_tools("gemini,claude,copilot") == ["gemini", "claude", "copilot"]

def test_parse_tools_strips_whitespace():
    assert parse_tools(" gemini , claude ") == ["gemini", "claude"]

def test_parse_tools_deduplicates():
    assert parse_tools("gemini,gemini,claude") == ["gemini", "claude"]

def test_parse_tools_invalid():
    with pytest.raises(click.BadParameter, match="Invalid tool"):
        parse_tools("gemini,foobar")

def test_parse_tools_empty():
    with pytest.raises(click.BadParameter, match="At least one tool"):
        parse_tools("")


# --- Factory tests ---

def test_create_provider_gemini():
    from context_scribe.observer.gemini_provider import GeminiProvider
    p = create_provider("gemini")
    assert isinstance(p, GeminiProvider)

def test_create_provider_copilot():
    from context_scribe.observer.copilot_provider import CopilotProvider
    p = create_provider("copilot")
    assert isinstance(p, CopilotProvider)

def test_create_provider_claude():
    from context_scribe.observer.claude_provider import ClaudeProvider
    p = create_provider("claude")
    assert isinstance(p, ClaudeProvider)

def test_create_provider_unknown():
    assert create_provider("foobar") is None

def test_create_evaluator_claude():
    from context_scribe.evaluator.claude_llm import ClaudeEvaluator
    with patch("subprocess.run"):
        e = create_evaluator("claude")
    assert isinstance(e, ClaudeEvaluator)

def test_create_evaluator_default():
    from context_scribe.evaluator.llm import Evaluator
    with patch("subprocess.run"):
        e = create_evaluator("gemini")
    assert isinstance(e, Evaluator)
