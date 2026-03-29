# Contributing to Context-Scribe

Thank you for your interest in contributing to Context-Scribe! This document provides guidelines and instructions for contributing to this project.

## 🏗 Architecture Overview

Context-Scribe follows an **Observer-Evaluator-Bridge** pattern:

1.  **Observer (Providers)**: Monitors tool-specific log files (e.g., Gemini CLI, Claude, Copilot) for new user interactions.
2.  **Evaluator**: An LLM-powered engine that analyzes interactions to extract persistent rules.
3.  **Bridge (MCP Client)**: Communicates with the `@allpepper/memory-bank-mcp` server to persist rules.

---

## 🛠 Adding New Tools (Providers)

Adding support for a new AI tool involves creating a new **Provider**. Providers are responsible for watching a specific directory and parsing its log format into a unified `Interaction` model.

### 1. Create the Provider Class
Create a new file in `context_scribe/observer/mytool_provider.py`. Your class must inherit from `BaseProvider`.

```python
from context_scribe.observer.base_provider import BaseProvider
import json

class MyToolProvider(BaseProvider):
    def __init__(self, log_dir: str = "~/.mytool/logs/"):
        # file_extension filters which files the watchdog monitors
        super().__init__(log_dir=log_dir, file_extension=".log")
        self._initialize_historical_logs()

    def _parse_historical_file(self, file_path: str):
        """
        Populate self.global_processed_ids with IDs of messages already in the file
        to avoid processing them when the daemon starts.
        """
        # Implement parsing logic here...
        pass

    def _parse_file_content(self, temp_path: str, original_path: str):
        """
        Parse the content of a (snapshot) log file and enqueue new interactions.
        """
        # 1. Determine the project name (usually from directory structure)
        project_name = "my-project" 
        
        # 2. Parse file and find NEW messages
        # 3. For each new message, call:
        # self._extract_interaction(msg_dict, project_name)
        # 4. Track processed IDs:
        # self._mark_id_processed(unique_msg_id)
```

### 2. Implement Bootstrapping (Optional)
If the tool requires a specific "Master Retrieval Directive" in its configuration (like `CLAUDE.md` or `GEMINI.md`), add a bootstrap function in `context_scribe/main.py`.

### 3. Register the Tool
Update `context_scribe/main.py`:
- Add your provider to the `run_daemon` logic.
- Add your tool to the `@click.choice` in the `cli` command.

---

## 🧠 Adding New Evaluators

Evaluators are the "brains" that decide what constitutes a rule.

### 1. Create the Evaluator Class
Inherit from `BaseEvaluator` in `context_scribe/evaluator/`.

```python
from context_scribe.evaluator.base_evaluator import BaseEvaluator

class MyNewEvaluator(BaseEvaluator):
    def _execute_cli(self, prompt: str) -> str:
        """
        Call your preferred LLM CLI (e.g., 'ollama run ...') 
        and return the raw string output.
        """
        # Run subprocess and return stdout
        pass
```

The `BaseEvaluator` handles prompt templating and JSON parsing automatically.

---

## 🧪 Testing Requirements

We maintain a strict **80% code coverage** requirement.

- **Unit Tests**: Place in `tests/`. Use `pytest`.
- **Mocks**: Use `unittest.mock` to avoid actual CLI calls during tests.
- **Running Tests**:
  ```bash
  pytest --cov=context_scribe tests/
  ```

---

## 📜 Code Style & Standards

- **Type Hints**: Use type hints for all function signatures.
- **Async/Await**: The core loop is asynchronous. Ensure any I/O-bound tasks use `asyncio` or are run in executors if they are blocking (like the `watchdog` iterator).
- **Logging**: Use the standard `logging` module. Avoid `print()` in core logic (the Dashboard uses `rich` for UI).
- **Docstrings**: Provide Google-style docstrings for public classes and methods.

## 🚀 Submission Process

1.  Fork the repository.
2.  Create a feature branch (`git checkout -b feature/amazing-tool`).
3.  Ensure all tests pass and coverage is maintained.
4.  Submit a Pull Request with a clear description of changes.
