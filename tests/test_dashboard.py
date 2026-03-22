from context_scribe.main import Dashboard

def test_dashboard_initialization():
    db = Dashboard("gemini")
    assert db.tool == "gemini"
    assert db.update_count == 0
    assert len(db.history) == 0

def test_dashboard_add_history():
    db = Dashboard("gemini")
    db.add_history("global/global_rules.md")
    assert db.update_count == 1
    assert len(db.history) == 1
    assert db.history[0][1] == "global/global_rules.md"

def test_dashboard_history_limit():
    db = Dashboard("gemini")
    for i in range(15):
        db.add_history(f"file_{i}.md")
    assert len(db.history) == 10
    assert db.history[0][1] == "file_14.md"
