from context_scribe.main import Dashboard

def test_dashboard_initialization():
    db = Dashboard(["gemini"], "~/.memory-bank")
    assert db.tool == "gemini"
    assert db.bank_path == "~/.memory-bank"
    assert db.update_count == 0
    assert len(db.history) == 0

def test_dashboard_multi_initialization():
    db = Dashboard(["gemini", "claude", "copilot"], "~/.memory-bank")
    assert db.tools == ["gemini", "claude", "copilot"]
    assert len(db.tool_status) == 3
    for t in db.tools:
        assert db.tool_status[t] == "Initializing..."

def test_dashboard_add_history():
    db = Dashboard(["gemini"], "~/.memory-bank")
    db.add_history("global/global_rules.md", "Added rule")
    assert db.update_count == 1
    assert len(db.history) == 1
    assert db.history[0][2] == "global/global_rules.md"
    assert db.history[0][3] == "Added rule"

def test_dashboard_add_history_with_tool():
    db = Dashboard(["gemini", "claude"], "~/.memory-bank")
    db.add_history("global/global_rules.md", "Added rule", tool="gemini")
    assert db.history[0][1] == "gemini"

def test_dashboard_history_limit():
    db = Dashboard(["gemini"], "~/.memory-bank")
    for i in range(15):
        db.add_history(f"file_{i}.md", f"desc_{i}")
    assert len(db.history) == 10
    assert db.history[0][2] == "file_14.md"
    assert db.history[0][3] == "desc_14"

def test_dashboard_set_tool_status():
    db = Dashboard(["gemini", "claude"], "~/.memory-bank")
    db.set_tool_status("gemini", "🔍 Watching")
    db.set_tool_status("claude", "🧠 Thinking")
    assert db.tool_status["gemini"] == "🔍 Watching"
    assert db.tool_status["claude"] == "🧠 Thinking"

def test_dashboard_generate_layout_multi():
    db = Dashboard(["gemini", "claude", "copilot"], "~/.memory-bank")
    db.set_tool_status("gemini", "✅ SUCCESS")
    db.set_tool_status("claude", "🔍 Watching")
    db.set_tool_status("copilot", "🤔 Analyzing")
    layout = db.generate_layout()
    assert layout is not None
    assert layout["status"] is not None
    assert layout["history"] is not None
