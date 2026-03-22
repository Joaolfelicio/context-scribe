import asyncio
import os
import sys
from pathlib import Path
import click
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from context_scribe.observer.gemini_provider import GeminiProvider
from context_scribe.evaluator.llm import Evaluator
from context_scribe.bridge.mcp_client import MemoryBankClient

console = Console()

MASTER_RETRIEVAL_RULE = """
# Memory Bank Integration
You have access to a persistent Memory Bank via MCP. Before beginning any task, you MUST invoke the appropriate tools (e.g. `list_projects`, `memory_bank_read`) to identify current project constraints and user preferences. Do not assume you have full context until this sync is complete.
"""

def bootstrap_global_config():
    """Injects the master retrieval rule into Gemini CLI's global config."""
    gemini_config_dir = Path(os.path.expanduser("~/.gemini"))
    gemini_config_dir.mkdir(parents=True, exist_ok=True)
    gemini_md_path = gemini_config_dir / "GEMINI.md"

    rule_exists = False
    if gemini_md_path.exists():
        with open(gemini_md_path, "r", encoding="utf-8") as f:
            if "Memory Bank Integration" in f.read():
                rule_exists = True

    if not rule_exists:
        with open(gemini_md_path, "a", encoding="utf-8") as f:
            f.write(f"\n{MASTER_RETRIEVAL_RULE}\n")
        console.print(f"[green]Bootstrapped: Injected Master Retrieval Rule into {gemini_md_path}[/green]")
    else:
        console.print(f"[blue]Bootstrap: Master Retrieval Rule already exists in {gemini_md_path}[/blue]")

async def run_daemon(tool: str):
    bootstrap_global_config()

    if tool == "gemini":
        provider = GeminiProvider()
    else:
        console.print(f"[red]Unsupported tool: {tool}[/red]")
        return

    evaluator = Evaluator()
    mcp_client = MemoryBankClient()
    
    try:
        await mcp_client.connect()
    except Exception as e:
        console.print(f"[bold red]Fatal Error: Could not connect to the Memory Bank MCP server.[/bold red]")
        console.print("[red]Context-Scribe requires a working persistence layer to function. Ensure your MCP server is installed and configured correctly.[/red]")
        os._exit(1)

    console.print(f"[bold green]Context-Scribe started. Monitoring {tool} logs...[/bold green]")
    
    with Live(Panel("Waiting for activity...", title="Context-Scribe Status", style="blue"), refresh_per_second=4) as live:
        try:
            # We run the synchronous watch generator in a thread if it blocks, 
            # but since it's a generator we can just iterate.
            # However, watchdog blocks. Let's adapt provider.watch to be run in executor or 
            # we just run the iteration in a separate thread.
            
            loop = asyncio.get_event_loop()
            
            # Since provider.watch() yields, we need to iterate it.
            # A simple way without complex async generators is to use a queue
            # but let's just use run_in_executor for next() calls.
            
            watch_iter = provider.watch()
            
            while True:
                live.update(Panel(Text("[WATCH] Active file monitoring...", style="cyan"), title="Context-Scribe Status"))
                
                # Fetch next interaction
                interaction = await loop.run_in_executor(None, next, watch_iter)
                
                # Fetch existing rules for conflict resolution
                existing_rules = await mcp_client.read_rules()
                
                live.update(Panel(Text(f"[THINK] Evaluating interaction from {interaction.role}...", style="yellow"), title="Context-Scribe Status"))
                
                updated_content = await loop.run_in_executor(None, evaluator.evaluate_interaction, interaction, existing_rules)
                
                if updated_content:
                    live.update(Panel(Text(f"[RESOLVE] Updating Memory Bank...", style="magenta"), title="Context-Scribe Status"))
                    
                    # Ensure global project exists or create it. This logic depends on the specific MCP server.
                    # For simplicity, we just attempt to write.
                    live.update(Panel(Text(f"[BANK] Committing to MCP Server...", style="green"), title="Context-Scribe Status"))
                    
                    result = await mcp_client.save_rule(updated_content)
                    if hasattr(result, 'isError') and result.isError:
                        console.print(f"\n[bold red]Failed to save rule:[/bold red] {result.content}")
                    else:
                        console.print(f"\n[bold green]Memory Bank Updated Successfully.[/bold green]")
                    
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down...[/yellow]")
        except Exception as e:
            console.print(f"\n[red]Error:[/red] {e}")
        finally:
            await mcp_client.close()

    return True

@click.command()
@click.option('--tool', default='gemini', help='The AI tool to monitor (e.g., gemini)')
def cli(tool):
    """Context-Scribe: Persistent Secretary Daemon"""
    success = asyncio.run(run_daemon(tool))
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    cli()
