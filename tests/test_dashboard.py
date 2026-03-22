from context_scribe.main import Dashboard

def test_dashboard_initialization():
    db = Dashboard("gemini", "~/.memory-bank")
    assert db.tool == "gemini"
    assert db.bank_path == "~/.memory-bank"
    assert db.update_count == 0
    assert len(db.history) == 0

def test_dashboard_add_history():
    db = Dashboard("gemini", "~/.memory-bank")
    db.add_history("global/global_rules.md", "Added rule")
    assert db.update_count == 1
    assert len(db.history) == 1
    assert db.history[0][1] == "global/global_rules.md"
    assert db.history[0][2] == "Added rule"

def test_dashboard_history_limit():
    db = Dashboard("gemini", "~/.memory-bank")
    for i in range(15):
        db.add_history(f"file_{i}.md", f"desc_{i}")
    assert len(db.history) == 10
    assert db.history[0][1] == "file_14.md"
    assert db.history[0][2] == "desc_14"
