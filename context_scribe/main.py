import asyncio
import os
import sys
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set
import click
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from rich.table import Table
from rich.spinner import Spinner

from context_scribe.observer.gemini_provider import GeminiProvider
from context_scribe.observer.copilot_provider import CopilotProvider
from context_scribe.observer.claude_provider import ClaudeProvider
from context_scribe.evaluator.llm import Evaluator, RuleOutput
from context_scribe.evaluator.claude_llm import ClaudeEvaluator
from context_scribe.bridge.mcp_client import MemoryBankClient
from context_scribe.observer.provider import Interaction, BaseProvider

console: Console = Console()

VALID_TOOLS = ["gemini", "copilot", "claude"]

MASTER_RETRIEVAL_RULE = """
# Memory Bank Integration
You have access to a persistent Memory Bank via MCP. Before beginning any task, you MUST invoke the appropriate tools (e.g. `list_projects`, `memory_bank_read`) to identify current project constraints and user preferences.

**Rule Precedence:**
- If a project-specific rule (`rules.md` in the project folder) contradicts a global rule (`global_rules.md`), the **project-specific rule takes precedence**.
- Do not assume you have full context until this sync is complete.
"""


def create_provider(tool: str) -> Optional[BaseProvider]:
    """Factory: create the appropriate provider for a tool name."""
    if tool == "gemini":
        return GeminiProvider()
    elif tool == "copilot":
        return CopilotProvider()
    elif tool == "claude":
        return ClaudeProvider()
    return None


def create_evaluator(tool: str):
    """Factory: create the appropriate evaluator for a tool name."""
    if tool == "claude":
        return ClaudeEvaluator()
    return Evaluator()


def bootstrap_tool(tool: str) -> None:
    """Run the bootstrap config injection for a given tool."""
    if tool == "gemini":
        bootstrap_global_config()
    elif tool == "copilot":
        bootstrap_copilot_config()
    elif tool == "claude":
        bootstrap_claude_config()


class Dashboard:
    """Dashboard supporting one or more active tools."""

    def __init__(self, tools: List[str], bank_path: str):
        self.tools = tools
        self.bank_path = bank_path
        # Per-tool status tracking
        self.tool_status: Dict[str, str] = {t: "Initializing..." for t in tools}
        self.last_event_time = "N/A"
        self.update_count = 0
        self.history: List[tuple] = []  # (time, tool, file_path, description)

    # Backward-compat properties for single-tool usage and tests
    @property
    def tool(self) -> str:
        return self.tools[0] if self.tools else ""

    @property
    def status(self) -> str:
        if len(self.tools) == 1:
            return self.tool_status.get(self.tools[0], "")
        return "; ".join(f"{t}: {s}" for t, s in self.tool_status.items())

    @status.setter
    def status(self, value: str):
        # Set status for all tools (backward compat for single-tool mode)
        for t in self.tools:
            self.tool_status[t] = value

    def set_tool_status(self, tool: str, status: str):
        self.tool_status[tool] = status

    def add_history(self, file_path: str, description: str, tool: str = ""):
        self.update_count += 1
        self.last_event_time = datetime.now().strftime("%H:%M:%S")
        self.history.insert(0, (self.last_event_time, tool, file_path, description))
        if len(self.history) > 10:
            self.history.pop()

    def generate_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="status", size=3 + len(self.tools) * 2),
            Layout(name="history"),
            Layout(name="footer", size=3)
        )

        # Header
        tools_label = ", ".join(self.tools)
        header_text = Text.assemble(
            (" 📜 Context-Scribe ", "bold white on blue"),
            (f" Monitoring: {tools_label} ", "bold blue on white"),
            (f" 📂 Bank: {self.bank_path} ", "bold white on cyan")
        )
        layout["header"].update(Panel(header_text, style="blue", border_style="blue"))

        # Status Panel — one row per tool
        status_table = Table(expand=True, box=None, show_header=False)
        status_table.add_column("Tool", style="bold cyan", width=12)
        status_table.add_column("Status")

        for tool_name in self.tools:
            st = self.tool_status.get(tool_name, "")
            color = "cyan"
            if "🤔" in st:
                color = "yellow"
            elif "📖" in st:
                color = "blue"
            elif "🧠" in st:
                color = "bright_magenta"
            elif "📝" in st:
                color = "magenta"
            elif "✅" in st:
                color = "green"
            status_table.add_row(tool_name, Text(st, style=f"bold {color}"))

        layout["status"].update(Panel(
            status_table,
            title="Active Tasks",
            border_style="cyan",
            subtitle="Press Ctrl+C to stop"
        ))

        # History Panel
        history_table = Table(expand=True, box=None)
        history_table.add_column("Time", style="dim", width=10)
        history_table.add_column("Tool", style="bold cyan", width=10)
        history_table.add_column("Modified File", style="cyan")
        history_table.add_column("Description", style="dim")

        for time_str, tool_name, path, desc in self.history:
            history_table.add_row(time_str, tool_name, path, desc)

        layout["history"].update(Panel(
            history_table,
            title="Recent Modifications",
            border_style="dim"
        ))

        # Footer
        stats = Table.grid(expand=True)
        stats.add_column(justify="left")
        stats.add_column(justify="right")
        stats.add_row(
            Text(f" System: Active", style="green"),
            Text(f"Total Rules Extracted: {self.update_count} ", style="bold green")
        )
        layout["footer"].update(Panel(stats, border_style="dim"))

        return layout

def bootstrap_global_config() -> None:
    """Injects the master retrieval rule into Gemini CLI's global config."""
    config_path = os.path.expanduser("~/.gemini")
    gemini_config_dir: Path = Path(config_path)
    gemini_config_dir.mkdir(parents=True, exist_ok=True)
    gemini_md_path: Path = gemini_config_dir / "GEMINI.md"

    rule_up_to_date = False
    if gemini_md_path.exists():
        with open(gemini_md_path, "r", encoding="utf-8") as f:
            content = f.read()
            if "Rule Precedence:" in content:
                rule_up_to_date = True

    if not rule_up_to_date:
        with open(gemini_md_path, "a", encoding="utf-8") as f:
            f.write(f"\n{MASTER_RETRIEVAL_RULE}\n")

def bootstrap_copilot_config() -> None:
    """Injects the master retrieval rule into GitHub Copilot's instructions file."""
    config_path = os.path.expanduser("~/.config/github-copilot")
    copilot_config_dir: Path = Path(config_path)
    copilot_config_dir.mkdir(parents=True, exist_ok=True)
    instructions_path: Path = copilot_config_dir / "instructions.md"

    rule_up_to_date = False
    if instructions_path.exists():
        with open(instructions_path, "r", encoding="utf-8") as f:
            content = f.read()
            if "# Memory Bank Integration" in content:
                rule_up_to_date = True

    if not rule_up_to_date:
        with open(instructions_path, "a", encoding="utf-8") as f:
            f.write(f"\n{MASTER_RETRIEVAL_RULE}\n")

def bootstrap_claude_config() -> None:
    """Injects the master retrieval rule into Claude Code's global config."""
    config_path = os.path.expanduser("~/.claude")
    claude_config_dir: Path = Path(config_path)
    claude_config_dir.mkdir(parents=True, exist_ok=True)
    claude_md_path: Path = claude_config_dir / "CLAUDE.md"

    rule_up_to_date = False
    if claude_md_path.exists():
        with open(claude_md_path, "r", encoding="utf-8") as f:
            content = f.read()
            if "Rule Precedence:" in content:
                rule_up_to_date = True

    if not rule_up_to_date:
        with open(claude_md_path, "a", encoding="utf-8") as f:
            f.write(f"\n{MASTER_RETRIEVAL_RULE}\n")


class SharedDeduplication:
    """Thread-safe shared deduplication across multiple provider pipelines.

    Tracks rule descriptions that have already been committed so that
    the same rule extracted by one provider is not written again when
    another provider encounters the same user interaction.
    """

    def __init__(self):
        self._seen: Set[str] = set()
        self._lock = threading.Lock()

    def is_duplicate(self, rule_output: RuleOutput) -> bool:
        """Return True if this rule has already been committed."""
        key = f"{rule_output.scope}:{rule_output.content.strip()}"
        with self._lock:
            return key in self._seen

    def mark_committed(self, rule_output: RuleOutput) -> None:
        """Record a rule as committed."""
        key = f"{rule_output.scope}:{rule_output.content.strip()}"
        with self._lock:
            self._seen.add(key)


async def _run_tool_pipeline(
    tool: str,
    provider: BaseProvider,
    evaluator,
    mcp_client: MemoryBankClient,
    dashboard: Dashboard,
    dedup: SharedDeduplication,
    live: Live,
) -> None:
    """Run the watch-evaluate-commit loop for a single tool.

    Designed to be used as a concurrent coroutine alongside other tools.
    """
    loop = asyncio.get_event_loop()
    watch_iter = provider.watch()
    dashboard.set_tool_status(tool, "🔍 Watching log stream...")

    while True:
        live.update(dashboard.generate_layout())
        interaction = await loop.run_in_executor(None, next, watch_iter)
        if interaction is None:
            continue

        dashboard.set_tool_status(tool, f"🤔 Analyzing user message ({interaction.project_name})")
        live.update(dashboard.generate_layout())

        # Reading bank
        dashboard.set_tool_status(tool, f"📖 Accessing Memory Bank ({interaction.project_name})...")
        live.update(dashboard.generate_layout())
        existing_global = await mcp_client.read_rules("global", "global_rules.md")
        existing_project = await mcp_client.read_rules(interaction.project_name, "rules.md")

        # Evaluating
        dashboard.set_tool_status(tool, f"🧠 Thinking: Extracting rules for {interaction.project_name}...")
        live.update(dashboard.generate_layout())
        rule_output = await loop.run_in_executor(
            None, evaluator.evaluate_interaction, interaction, existing_global, existing_project
        )

        if rule_output:
            # Cross-provider deduplication
            if dedup.is_duplicate(rule_output):
                dashboard.set_tool_status(tool, "🔍 Watching log stream... (skipped duplicate)")
                continue

            dest_proj = "global" if rule_output.scope == "GLOBAL" else interaction.project_name
            dest_file = "global_rules.md" if rule_output.scope == "GLOBAL" else "rules.md"
            dest_path = f"{dest_proj}/{dest_file}"

            # Deduplicate content lines
            lines = rule_output.content.splitlines()
            seen_lines: Set[str] = set()
            unique_lines: List[str] = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("-") and stripped in seen_lines:
                    continue
                unique_lines.append(line)
                if stripped.startswith("-"):
                    seen_lines.add(stripped)

            deduped_content = "\n".join(unique_lines).strip()

            dashboard.set_tool_status(tool, f"📝 Committing: {dest_path}")
            live.update(dashboard.generate_layout())
            await mcp_client.save_rule(deduped_content, dest_proj, dest_file)

            dedup.mark_committed(rule_output)
            dashboard.add_history(dest_path, rule_output.description, tool=tool)
            dashboard.set_tool_status(tool, f"✅ SUCCESS: Updated {dest_path}")
            live.update(dashboard.generate_layout())
            console.print(
                f"[bold green]▶ UPDATED ({tool}):[/bold green] [cyan]{dest_path}[/cyan] ({rule_output.description})"
            )
            await asyncio.sleep(2)

        dashboard.set_tool_status(tool, "🔍 Watching log stream...")


async def run_daemon(tool: str, bank_path: str) -> bool:
    """Run daemon for a single tool (backward-compatible entry point)."""
    return await run_daemon_multi([tool], bank_path)


async def run_daemon_multi(tools: List[str], bank_path: str) -> bool:
    """Run daemon for one or more tools concurrently."""
    # Validate and create providers + evaluators
    providers: Dict[str, BaseProvider] = {}
    evaluators: Dict[str, object] = {}

    for tool in tools:
        bootstrap_tool(tool)
        provider = create_provider(tool)
        if not provider:
            return False
        providers[tool] = provider
        evaluators[tool] = create_evaluator(tool)

    # Shared MCP bridge client
    mcp_client = MemoryBankClient(bank_path=bank_path)

    try:
        await mcp_client.connect()
    except Exception:
        console.print("[bold red]Fatal Error: Could not connect to the Memory Bank MCP server.[/bold red]")
        os._exit(1)

    dedup = SharedDeduplication()
    db = Dashboard(tools, bank_path)

    with Live(db.generate_layout(), refresh_per_second=10, screen=True) as live:
        try:
            # Launch a concurrent pipeline for each tool
            tasks = []
            for tool in tools:
                task = asyncio.create_task(
                    _run_tool_pipeline(
                        tool=tool,
                        provider=providers[tool],
                        evaluator=evaluators[tool],
                        mcp_client=mcp_client,
                        dashboard=db,
                        dedup=dedup,
                        live=live,
                    )
                )
                tasks.append(task)

            # Wait until interrupted
            await asyncio.gather(*tasks)
        except (KeyboardInterrupt, asyncio.CancelledError):
            for t in tasks:
                t.cancel()
            db.status = "🛑 Stopping..."
            live.update(db.generate_layout())
        finally:
            await mcp_client.close()
    return True


def parse_tools(tools_str: str) -> List[str]:
    """Parse a comma-separated tools string into a validated list."""
    raw = [t.strip().lower() for t in tools_str.split(",") if t.strip()]
    invalid = [t for t in raw if t not in VALID_TOOLS]
    if invalid:
        raise click.BadParameter(
            f"Invalid tool(s): {', '.join(invalid)}. Valid choices: {', '.join(VALID_TOOLS)}"
        )
    if not raw:
        raise click.BadParameter("At least one tool must be specified.")
    # Remove duplicates while preserving order
    seen: Set[str] = set()
    result: List[str] = []
    for t in raw:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


@click.command()
@click.option(
    '--tools',
    'tools_str',
    default=None,
    help='Comma-separated list of AI tools to monitor (e.g. gemini,claude,copilot)'
)
@click.option(
    '--tool',
    'single_tool',
    default=None,
    type=click.Choice(VALID_TOOLS),
    help='Single AI tool to monitor (backward-compatible; use --tools for multiple)'
)
@click.option('--bank-path', default='~/.memory-bank', help='Path to your Memory Bank root')
def cli(tools_str, single_tool, bank_path):
    """Context-Scribe: Persistent Secretary Daemon"""
    # Resolve which tools to run
    if tools_str and single_tool:
        raise click.UsageError("Use --tools or --tool, not both.")
    if tools_str:
        tools = parse_tools(tools_str)
    elif single_tool:
        tools = [single_tool]
    else:
        tools = ["gemini"]  # default

    try:
        asyncio.run(run_daemon_multi(tools, bank_path))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    cli()
