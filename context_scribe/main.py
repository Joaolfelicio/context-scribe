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
    def __init__(self, tool: str):
        self.tool = tool
        self.status = "Initializing..."
        self.last_event_time = "N/A"
        self.update_count = 0
        self.history: list[tuple[str, str]] = []  # List of (time, file_path) tuples

    def add_history(self, file_path: str):
        self.update_count += 1
        self.last_event_time = datetime.now().strftime("%H:%M:%S")
        self.history.insert(0, (self.last_event_time, file_path))
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
        
        # Header
        header_text = Text.assemble(
            (" 📜 Context-Scribe ", "bold white on blue"),
            (f" Monitoring: {self.tool} ", "bold blue on white")
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
            border_style=status_color
        ))

        # History Panel (Bottom)
        history_table = Table(expand=True, box=None)
        history_table.add_column("Time", style="dim", width=10)
        history_table.add_column("Modified File", style="cyan")
        
        for time, path in self.history:
            history_table.add_row(time, path)
            
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
    gemini_config_dir = Path(os.path.expanduser("~/.gemini"))
    gemini_config_dir.mkdir(parents=True, exist_ok=True)
    gemini_md_path = gemini_config_dir / "GEMINI.md"

    current_content = ""
    if gemini_md_path.exists():
        current_content = gemini_md_path.read_text(encoding="utf-8")

    if "Rule Precedence:" not in current_content:
        # If an old version of the integration section exists, replace it
        if "# Memory Bank Integration" in current_content:
            # Simple replacement of the existing section
            import re
            pattern = r"# Memory Bank Integration.*?(?=#|$)"
            new_content = re.sub(pattern, MASTER_RETRIEVAL_RULE.strip(), current_content, flags=re.DOTALL)
            gemini_md_path.write_text(new_content, encoding="utf-8")
        else:
            # Append if nothing found
            with open(gemini_md_path, "a", encoding="utf-8") as f:
                f.write(f"\n{MASTER_RETRIEVAL_RULE}\n")

async def run_daemon(tool: str) -> bool:
    bootstrap_global_config()
    provider = GeminiProvider() if tool == "gemini" else None
    if not provider: return False

    evaluator = Evaluator()
    mcp_client = MemoryBankClient()
    
    try:
        await mcp_client.connect()
    except Exception:
        console.print("[bold red]MCP Connection Failed.[/bold red]")
        sys.exit(1)

    db = Dashboard(tool)
    with Live(db.generate_layout(), refresh_per_second=10, screen=True) as live:
        try:
            loop = asyncio.get_event_loop()
            watch_iter = provider.watch()
            db.status = "🔍 Watching log stream..."

            while True:
                live.update(db.generate_layout())
                interaction = await loop.run_in_executor(None, next, watch_iter)
                
                db.status = f"🤔 Analyzing: {interaction.project_name}"
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
                    
                    db.status = f"📝 Committing: {dest_path}"
                    live.update(db.generate_layout())
                    await mcp_client.save_rule(rule_output.content, dest_proj, dest_file)
                    
                    db.add_history(dest_path)
                    db.status = f"✅ SUCCESS: Updated {dest_path}"
                    live.update(db.generate_layout())
                    await asyncio.sleep(2)
                
                db.status = "🔍 Watching log stream..."
        except KeyboardInterrupt:
            pass
        finally:
            await mcp_client.close()
    return True

@click.command()
@click.option('--tool', default='gemini', help='The AI tool to monitor (e.g., gemini)')
def cli(tool: str) -> None:
    """Context-Scribe: Persistent Secretary Daemon"""
    asyncio.run(run_daemon(tool))

if __name__ == "__main__":
    cli()
