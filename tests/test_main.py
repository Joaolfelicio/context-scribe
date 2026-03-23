from unittest.mock import patch
from context_scribe.main import bootstrap_global_config, bootstrap_copilot_config, Dashboard

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

def test_dashboard_generate_layout():
    db = Dashboard("gemini", "~/.memory-bank")
    db.status = "✅ SUCCESS"
    layout = db.generate_layout()
    assert layout is not None
    # Check if history is displayed
    db.add_history("test.md", "Update text")
    layout = db.generate_layout()
    # Check if some component contains the text
    assert layout["history"] is not None
