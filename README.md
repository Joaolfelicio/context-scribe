# 📜 Context-Scribe

**Context-Scribe** is a "Persistent Secretary" daemon designed to eliminate "Agent Amnesia." It monitors local AI session logs in the background, extracts long-term behavioral rules and project constraints, and professionally persists them to a centralized Memory Bank via the Model Context Protocol (MCP).

![Context-Scribe Dashboard](docs/dashboard-ui-render.png)

## 🚀 Core Features

*   **🔄 Zero-Touch Sync**: Automatically extracts and persists rules natively from chat logs, entirely out of band.
*   **📂 Project-Aware Routing**: Intelligently detects the active project context and routes rules to either `global/global_rules.md` or `[project-name]/rules.md`.
*   **⚖️ Strength Hierarchy**: Enforces a "Project > Global" hierarchy. Project-specific rules always take precedence over global ones.
*   **🧠 Intelligent Enhancement**: Does not just copy-paste; the system professionalizes slang (e.g., "spongebob typing" -> "alternating uppercase") and adds concrete code examples.
*   **🏗️ Semantic Categorization**: Automatically organizes your Memory Bank into logical Markdown sections like `# Style`, `# Architecture`, and `# Personal`.
*   **🛡️ Conflict Resolution**: Implements "New-Trumps-Old" logic to autonomously resolve contradictions within the same scope.
*   **⚡ Ultra-Fast Evaluation**: Uses optimized, extension-free headless calls to `gemini-2.5-flash-lite` for near-instant extraction.

## 🏗️ Architecture

Context-Scribe operates on an **Observer-Evaluator-Bridge** pattern:
1.  **Observer**: A robust `watchdog` powered log monitor with manual periodic scanning ensuring zero missed events across various Gemini log formats.
2.  **Evaluator**: Headless evaluation powered by your local `gemini` CLI (no extra API keys required).
3.  **Bridge**: Direct MCP integration syncing data into `@allpepper/memory-bank-mcp`.

## 📋 Prerequisites

*   **Python 3.10+**
*   **Gemini CLI**: The daemon currently uses the local `gemini` CLI for headless evaluation.
*   **Memory Bank MCP**: Your AI tool (e.g., Gemini CLI) **must** have the `@allpepper/memory-bank-mcp` server configured and trusted to correctly retrieve the memories persisted by Context-Scribe.

> **Note**: Currently, only **Gemini CLI** is supported as a log source and evaluator. We have designed the architecture to be extensible and plan to support other AI tools (like Claude/Cline) in the future.

## 🛠️ Installation & Setup

Ensure you have Python 3.10+ installed.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Joaolfelicio/context-scribe.git
    cd context-scribe
    ```

2.  **Set up a virtual environment:**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install the package:**
    ```bash
    pip install -e ".[test]"
    ```

## 📖 Usage

Start the production daemon:
```bash
context-scribe --tool gemini
```

### Integration
Upon running, `context-scribe` will bootstrap your `~/.gemini/GEMINI.md` file globally to ensure agents inherently know how to query the persistent memory via MCP. Ensure you have the corresponding memory-bank server correctly configured within your Gemini CLI setup.

## 🧪 Testing

We maintain a high standard of quality with a **hard requirement of at least 80% code coverage**.

### Running Tests
To verify the system components and logic:
```bash
pytest --cov=context_scribe tests/
```

### Manual Validation
1.  **Start the daemon**: `context-scribe --tool gemini`
2.  **Simulate a rule**: 
    ```bash
    echo '[{"role": "user", "content": "Rule: Always use single quotes for Python strings."}]' > ~/.gemini/tmp/test_rule.json
    ```
3.  **Verify**: Check `~/.memory-bank/global/global_rules.md` for the professionally enhanced and categorized rule.
