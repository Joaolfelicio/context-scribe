# Context-Scribe Roadmap

## 1. Core Architecture Refactoring
- [ ] **Abstract `Evaluator` Interface**: Create a `BaseEvaluator` protocol in `evaluator/__init__.py`.
- [ ] **Unified Provider-Evaluator Pairing**: Implement a factory or configuration system that ensures when Tool X is used as a `Provider`, it is also used as the `Evaluator`.
- [ ] **Dynamic Evaluator Loading**: Allow the daemon to load specific evaluators based on the `--tool` flag.

## 2. Multi-Tool Support
### ♊ Gemini CLI (Current)
- [ ] Refactor existing `Evaluator` into `GeminiEvaluator`.
- [ ] Ensure "Gemini Everywhere": Use headless Gemini CLI calls for both rule extraction and the "Should I Update?" pre-evaluation decision.

### 🧬 Claude / Cline
- [ ] **`ClaudeProvider`**: Implement log monitoring for Cline/Claude Desktop.
- [ ] **`ClaudeEvaluator`**: Implement evaluation using the Claude API or a relevant CLI tool (e.g., `anthropic` CLI).

### 🤖 GitHub Copilot
- [ ] **`CopilotProvider`**: Research and implement monitoring for VS Code Copilot logs.
- [ ] **`CopilotEvaluator`**: Implement rule extraction using Copilot (potentially via a custom extension or API if available).

## 3. Decision Logic Improvements
- [ ] **Two-Stage Evaluation**:
    1. **Relevance Check**: A lightweight, fast prompt to ask Tool X: *"Does this interaction contain a new persistent rule or preference?"*
    2. **Extraction Pass**: If (1) is true, perform the full "Professionalize & Consolidate" extraction.
- [ ] **Loop Prevention for All Tools**: Ensure each tool has a unique `INTERNAL_SIGNATURE` to prevent self-evaluating its own updates.

## 4. UI & DX
- [ ] **Tool Selection**: Add a clear indicator in the dashboard showing which tool is currently active for both observation and evaluation.
- [ ] **Multi-Tool Concurrent Support**: Allow the daemon to monitor multiple tools simultaneously (e.g., `context-scribe --tools gemini,claude`).
