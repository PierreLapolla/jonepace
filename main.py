import sys
from pathlib import Path
import questionary
from rich.console import Console
from rich.panel import Panel
from pedros import safe

from onepace.utils.cache import CacheManager
from onepace.core.metadata_manager import MetadataManager
from onepace.core.scanner import Scanner

console = Console()
cache_manager = CacheManager()
    
@safe
def main_menu():
    console.clear()
    console.print(Panel("[bold blue]One Pace for Jellyfin[/bold blue]\n[italic]Terminal Setup Tool[/italic]", expand=False))
    
    choices = ["Full run", "Clear cache", "Exit"]
    choice = questionary.select(
        "Select an option",
        choices=choices,
        default="Full run",
        use_indicator=True
    ).ask()
    
    if choice == "Full run":
        run_workflow()
    elif choice == "Clear cache":
        clear_cache()
    elif choice == "Exit" or choice is None:
        console.print("[yellow]Exiting...[/yellow]")
        sys.exit(0)

def run_workflow():
    console.print("[bold green]Starting Full Run...[/bold green]")
    
    # Step B: Metadata
    metadata_index = download_metadata()
    
    # Step C: Scan
    scan_existing_files(metadata_index)
    
    # Step D: Selection
    select_arcs(metadata_index)
    
    # Step E: Download
    download_episodes()
    
    # Step F: Build
    build_library()
    
    # Step G: Summary
    show_summary()


def download_metadata():
    console.print("[blue]Step B: Get / refresh dataset[/blue]")
    metadata_manager = MetadataManager(cache_manager)
    metadata_manager.download_and_extract()
    return metadata_manager.load_index()

def scan_existing_files(metadata_index):
    console.print("[blue]Step C: Scan for already-available episodes[/blue]")
    scanner = Scanner(cache_manager, metadata_index)
    scanner.scan()

def select_arcs(metadata_index):
    console.print("[blue]Step D: Arc selection[/blue]")
    
    if not metadata_index or not metadata_index["arcs"]:
        console.print("[red]No arcs found in metadata index.[/red]")
        return

    # Prepare choices with status info
    choices = []
    found_episode_paths = cache_manager.state["scan"]["found_episode_ids"]
    found_episode_names = [Path(p).stem for p in found_episode_paths]
    
    for arc in metadata_index["arcs"]:
        total = len(arc["episodes"])
        found = sum(1 for ep in arc["episodes"] if ep in found_episode_names)
        status = f"({found}/{total})"
        
        choices.append(questionary.Choice(
            title=f"{arc['name']} {status}",
            value=arc['name'],
            checked=arc['name'] in cache_manager.state["selection"]["selected_arc_ids"]
        ))

    selected = questionary.checkbox(
        "Select arcs to install (Space to toggle, Enter to confirm)",
        choices=choices
    ).ask()
    
    if selected is not None:
        cache_manager.state["selection"]["selected_arc_ids"] = selected
        cache_manager.save_state()
        console.print(f"[green]Selected {len(selected)} arcs.[/green]")

def download_episodes():
    console.print("[blue]Step E: Download missing episodes[/blue] (Placeholder)")
    # TODO: libtorrent implementation

def build_library():
    console.print("[blue]Step F: Build / finalize library[/blue] (Placeholder)")
    # TODO: Structure folders and move files

def show_summary():
    console.print("[blue]Step G: Summary[/blue] (Placeholder)")
    # TODO: Show installation results

def clear_cache():
    confirm = questionary.confirm("Are you sure you want to clear the cache?", default=False).ask()
    if confirm:
        cache_manager.clear()
        console.print("[red]Cache cleared.[/red]")


if __name__ == "__main__":
    main_menu()
