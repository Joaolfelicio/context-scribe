import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime
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
from context_scribe.evaluator.llm import Evaluator
from context_scribe.bridge.mcp_client import MemoryBankClient
from context_scribe.observer.provider import Interaction, BaseProvider

console: Console = Console()

MASTER_RETRIEVAL_RULE = """
# Memory Bank Integration
You have access to a persistent Memory Bank via MCP. Before beginning any task, you MUST invoke the appropriate tools (e.g. `list_projects`, `memory_bank_read`) to identify current project constraints and user preferences. 

**Rule Precedence:**
- If a project-specific rule (`rules.md` in the project folder) contradicts a global rule (`global_rules.md`), the **project-specific rule takes precedence**.
- Do not assume you have full context until this sync is complete.
"""

class Dashboard:
    def __init__(self, tool: str, bank_path: str):
        self.tool = tool
        self.bank_path = bank_path
        self.status = "Initializing..."
        self.last_event_time = "N/A"
        self.update_count = 0
        self.history = []  # List of (time, file_path, description) tuples

    def add_history(self, file_path: str, description: str):
        self.update_count += 1
        self.last_event_time = datetime.now().strftime("%H:%M:%S")
        self.history.insert(0, (self.last_event_time, file_path, description))
        if len(self.history) > 10:  # Keep last 10 updates
            self.history.pop()

    def generate_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="status", size=5),
            Layout(name="history"),
            Layout(name="footer", size=3)
        )
        
        # Header showing tool and bank path with high-contrast highlights
        header_text = Text.assemble(
            (" 📜 Context-Scribe ", "bold white on blue"),
            (f" Monitoring: {self.tool} ", "bold blue on white"),
            (f" 📂 Bank: {self.bank_path} ", "bold white on cyan")
        )
        layout["header"].update(Panel(header_text, style="blue", border_style="blue"))

        # Status Panel (Top)
        status_color = "cyan"
        if "🤔" in self.status: status_color = "yellow"
        elif "📖" in self.status: status_color = "blue"
        elif "🧠" in self.status: status_color = "bright_magenta"
        elif "📝" in self.status: status_color = "magenta"
        elif "✅" in self.status: status_color = "green"

        status_text = Text(f"\n{self.status}\n", justify="center", style=f"bold {status_color}")
        layout["status"].update(Panel(
            status_text,
            title="Active Task",
            border_style=status_color,
            subtitle="Press Ctrl+C to stop"
        ))

        # History Panel (Bottom)
        history_table = Table(expand=True, box=None)
        history_table.add_column("Time", style="dim", width=10)
        history_table.add_column("Modified File", style="cyan")
        history_table.add_column("Description", style="dim")
        
        for time, path, desc in self.history:
            history_table.add_row(time, path, desc)
            
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

async def run_daemon(tool: str, bank_path: str) -> bool:
    if tool == "gemini":
        bootstrap_global_config()
        provider = GeminiProvider()
    elif tool == "copilot":
        bootstrap_copilot_config()
        provider = CopilotProvider()
    else:
        provider = None
    if not provider: return False

    evaluator = Evaluator()
    mcp_client = MemoryBankClient(bank_path=bank_path)
    
    try:
        await mcp_client.connect()
    except Exception:
        console.print("[bold red]Fatal Error: Could not connect to the Memory Bank MCP server.[/bold red]")
        os._exit(1)

    db = Dashboard(tool, bank_path)
    with Live(db.generate_layout(), refresh_per_second=10, screen=True) as live:
        try:
            loop = asyncio.get_event_loop()
            watch_iter = provider.watch()
            db.status = "🔍 Watching log stream..."

            while True:
                live.update(db.generate_layout())
                interaction = await loop.run_in_executor(None, next, watch_iter)
                if interaction is None:
                    continue
                
                db.status = f"🤔 Analyzing user message ({interaction.project_name})"
                live.update(db.generate_layout())
                
                # Reading bank
                db.status = f"📖 Accessing Memory Bank ({interaction.project_name})..."
                live.update(db.generate_layout())
                existing_global = await mcp_client.read_rules("global", "global_rules.md")
                existing_project = await mcp_client.read_rules(interaction.project_name, "rules.md")
                
                # Evaluating
                db.status = f"🧠 Thinking: Extracting rules for {interaction.project_name}..."
                live.update(db.generate_layout())
                rule_output = await loop.run_in_executor(None, evaluator.evaluate_interaction, interaction, existing_global, existing_project)
                
                if rule_output:
                    dest_proj = "global" if rule_output.scope == "GLOBAL" else interaction.project_name
                    dest_file = "global_rules.md" if rule_output.scope == "GLOBAL" else "rules.md"
                    dest_path = f"{dest_proj}/{dest_file}"
                    
                    # Deduplicate content lines
                    lines = rule_output.content.splitlines()
                    seen = set()
                    unique_lines = []
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith("-") and stripped in seen:
                            continue
                        unique_lines.append(line)
                        if stripped.startswith("-"):
                            seen.add(stripped)
                    
                    deduped_content = "\n".join(unique_lines).strip()

                    db.status = f"📝 Committing: {dest_path}"
                    live.update(db.generate_layout())
                    await mcp_client.save_rule(deduped_content, dest_proj, dest_file)
                    
                    db.add_history(dest_path, rule_output.description)
                    db.status = f"✅ SUCCESS: Updated {dest_path}"
                    live.update(db.generate_layout())
                    console.print(f"[bold green]▶ UPDATED:[/bold green] [cyan]{dest_path}[/cyan] ({rule_output.description})")
                    await asyncio.sleep(2)
                
                db.status = "🔍 Watching log stream..."
        except (KeyboardInterrupt, asyncio.CancelledError):
            db.status = "🛑 Stopping..."
            live.update(db.generate_layout())
        finally:
            await mcp_client.close()
    return True

@click.command()
@click.option('--tool', default='gemini', help='The AI tool to monitor')
@click.option('--bank-path', default='~/.memory-bank', help='Path to your Memory Bank root')
def cli(tool, bank_path):
    """Context-Scribe: Persistent Secretary Daemon"""
    try:
        asyncio.run(run_daemon(tool, bank_path))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    cli()
