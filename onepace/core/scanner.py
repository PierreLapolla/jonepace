import os
from pathlib import Path
from rich.console import Console

console = Console()

class Scanner:
    def __init__(self, cache_manager, metadata_index=None):
        self.cache_manager = cache_manager
        self.output_dir = Path(cache_manager.state["paths"]["output_dir"])
        self.metadata_index = metadata_index

    def scan(self):
        console.print(f"[yellow]Scanning {self.output_dir.absolute()} for existing episodes...[/yellow]")
        
        found_episodes = []
        found_episode_names = []
        
        # We look for .mkv files in One Pace/ subdirectory and current directory
        search_paths = [self.output_dir, self.output_dir / "One Pace"]
        
        for path in search_paths:
            if path.exists():
                for root, dirs, files in os.walk(path):
                    for file in files:
                        if file.endswith(".mkv"):
                            full_path = Path(root) / file
                            episode_name = full_path.stem
                            
                            # If we have a metadata index, we can verify if this is a valid episode
                            if self.metadata_index:
                                if episode_name in self.metadata_index["episodes"]:
                                    if episode_name not in found_episode_names:
                                        found_episodes.append(str(full_path))
                                        found_episode_names.append(episode_name)
                            else:
                                # Fallback: just add it if no index
                                if str(full_path) not in found_episodes:
                                    found_episodes.append(str(full_path))
        
        self.cache_manager.state["scan"]["found_episode_ids"] = found_episodes
        self.cache_manager.state["scan"]["completed"] = True
        self.cache_manager.save_state()
        
        console.print(f"[green]Scan complete. Found {len(found_episodes)} valid existing episodes.[/green]")
        return found_episodes
