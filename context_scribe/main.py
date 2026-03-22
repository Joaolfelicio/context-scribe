import asyncio
import os
import sys
import re
from pathlib import Path
from datetime import datetime
import click
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout
from rich.table import Table

from context_scribe.observer.gemini_provider import GeminiProvider
from context_scribe.evaluator.llm import Evaluator
from context_scribe.bridge.mcp_client import MemoryBankClient
from context_scribe.observer.provider import Interaction

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
        self.history = []  # List of (time, file_path, description) tuples

    def add_history(self, file_path: str, description: str):
        self.update_count += 1
        self.last_event_time = datetime.now().strftime("%H:%M:%S")
        self.history.insert(0, (self.last_event_time, file_path, description))
        if len(self.history) > 10:
            self.history.pop()

    def generate_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="status", size=5),
            Layout(name="history"),
            Layout(name="footer", size=3)
        )
        
        header_text = Text.assemble(
            (" 📜 Context-Scribe ", "bold white on blue"),
            (f" Monitoring: {self.tool} ", "bold blue on white")
        )
        layout["header"].update(Panel(header_text, style="blue", border_style="blue"))

        status_color = "cyan"
        if "🤔" in self.status: status_color = "yellow"
        elif "📖" in self.status: status_color = "blue"
        elif "🧠" in self.status: status_color = "bright_magenta"
        elif "📝" in self.status: status_color = "magenta"
        elif "✅" in self.status: status_color = "green"

        status_text = Text(f"\n{self.status}\n", justify="center", style=f"bold {status_color}")
        layout["status"].update(Panel(status_text, title="Active Task", border_style=status_color))

        history_table = Table(expand=True, box=None)
        history_table.add_column("Time", style="dim", width=10)
        history_table.add_column("Modified File", style="cyan", width=30)
        history_table.add_column("Description", style="white")
        
        for time, path, desc in self.history:
            history_table.add_row(time, path, desc)
            
        layout["history"].update(Panel(history_table, title="Recent Modifications", border_style="dim"))

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
    config_path = os.path.expanduser("~/.gemini")
    gemini_config_dir = Path(config_path)
    gemini_config_dir.mkdir(parents=True, exist_ok=True)
    gemini_md_path = gemini_config_dir / "GEMINI.md"

    if gemini_md_path.exists():
        with open(gemini_md_path, "r", encoding="utf-8") as f:
            if "Rule Precedence:" in f.read():
                return

    with open(gemini_md_path, "a", encoding="utf-8") as f:
        f.write(f"\n{MASTER_RETRIEVAL_RULE}\n")

def smart_merge(existing_content: str, new_rules: str) -> str:
    """Intelligently merges new rules into existing Markdown content."""
    if not existing_content.strip():
        return new_rules.strip()
    
    if new_rules.strip().lower() in existing_content.lower():
        return existing_content
    
    # Identify sections in the new rules (e.g., "### Style")
    sections = list(re.finditer(r'^(#+)\s+(.+)$', new_rules, re.MULTILINE))
    if not sections:
        return f"{existing_content.strip()}\n\n{new_rules.strip()}"
    
    merged_content = existing_content
    for i, match in enumerate(sections):
        header_title = match.group(2).strip()
        start = match.start()
        end = sections[i+1].start() if i+1 < len(sections) else len(new_rules)
        section_full = new_rules[start:end].strip()
        
        # Look for existing header
        existing_header = re.search(rf'^(#+)\s+{re.escape(header_title)}\s*$', merged_content, re.MULTILINE | re.IGNORECASE)
        
        if existing_header:
            # Find insertion point: end of this section
            header_level = len(existing_header.group(1))
            next_header = re.search(rf'^#{{1,{header_level}}}\s+', merged_content[existing_header.end():], re.MULTILINE)
            insert_pos = existing_header.end() + next_header.start() if next_header else len(merged_content)
            
            # Extract just rules (no header) from new section
            lines = section_full.splitlines()
            rules_only = "\n".join(lines[1:]).strip() if lines and lines[0].strip().startswith('#') else section_full
            
            if rules_only and rules_only.lower() not in merged_content[existing_header.start():insert_pos].lower():
                merged_content = merged_content[:insert_pos].rstrip() + "\n" + rules_only + "\n\n" + merged_content[insert_pos:].lstrip()
        else:
            merged_content = merged_content.strip() + "\n\n" + section_full
            
    return merged_content.strip()

async def run_daemon(tool: str) -> bool:
    bootstrap_global_config()
    provider = GeminiProvider() if tool == "gemini" else None
    if not provider: return False

    evaluator = Evaluator()
    mcp_client = MemoryBankClient()
    
    try:
        await mcp_client.connect()
    except Exception:
        console.print("[bold red]Fatal Error: Could not connect to the Memory Bank MCP server.[/bold red]")
        os._exit(1)
        return False

    db = Dashboard(tool)
    with Live(db.generate_layout(), refresh_per_second=10, screen=True) as live:
        try:
            loop = asyncio.get_event_loop()
            watch_iter = provider.watch()
            db.status = "🔍 Watching log stream..."

            while True:
                live.update(db.generate_layout())
                interaction = await loop.run_in_executor(None, next, watch_iter)
                
                db.status = f"🤔 Analyzing user message ({interaction.project_name})"
                live.update(db.generate_layout())
                
                existing_global = await mcp_client.read_rules("global", "global_rules.md")
                existing_project = await mcp_client.read_rules(interaction.project_name, "rules.md")
                
                db.status = f"🧠 Thinking: Extracting rules for {interaction.project_name}..."
                live.update(db.generate_layout())
                rule_output = await loop.run_in_executor(None, evaluator.evaluate_interaction, interaction, existing_global, existing_project)
                
                if rule_output:
                    dest_proj = "global" if rule_output.scope == "GLOBAL" else interaction.project_name
                    dest_file = "global_rules.md" if rule_output.scope == "GLOBAL" else "rules.md"
                    dest_path = f"{dest_proj}/{dest_file}"
                    
                    target_content = existing_global if rule_output.scope == "GLOBAL" else existing_project
                    merged_content = smart_merge(target_content, rule_output.content)
                    
                    if merged_content != target_content:
                        db.status = f"📝 Committing: {dest_path}"
                        live.update(db.generate_layout())
                        await mcp_client.save_rule(merged_content, dest_proj, dest_file)
                        db.add_history(dest_path, rule_output.description)
                        db.status = f"✅ SUCCESS: Updated {dest_path}"
                    else:
                        db.status = "✅ No changes needed"
                    
                    live.update(db.generate_layout())
                    await asyncio.sleep(2)
                
                db.status = "🔍 Watching log stream..."
        except KeyboardInterrupt:
            pass
        finally:
            await mcp_client.close()
    return True

@click.command()
@click.option('--tool', default='gemini', help='The AI tool to monitor')
def cli(tool: str):
    """Context-Scribe: Persistent Secretary Daemon"""
    asyncio.run(run_daemon(tool))

if __name__ == "__main__":
    cli()
