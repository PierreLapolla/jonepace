import os
import gdown
import zipfile
from pathlib import Path
from rich.console import Console

console = Console()

METADATA_GDRIVE_ID = "1NdEb7X0Rxjp7b_76BH9-TnObTClcASuB"

class MetadataManager:
    def __init__(self, cache_manager):
        self.cache_manager = cache_manager
        self.metadata_dir = Path(cache_manager.state["metadata"]["local_path"])

    def download_and_extract(self):
        output_zip = self.metadata_dir / "metadata.zip"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        
        if not self.cache_manager.state["metadata"]["downloaded"] or not output_zip.exists():
            console.print("[yellow]Downloading metadata...[/yellow]")
            try:
                gdown.download(id=METADATA_GDRIVE_ID, output=str(output_zip), quiet=False)
            except Exception as e:
                console.print(f"[red]Failed to download metadata: {e}[/red]")
                return

            console.print("[yellow]Extracting metadata...[/yellow]")
            try:
                with zipfile.ZipFile(output_zip, 'r') as zip_ref:
                    zip_ref.extractall(self.metadata_dir)
            except Exception as e:
                console.print(f"[red]Failed to extract metadata: {e}[/red]")
                return
            
            self.cache_manager.state["metadata"]["downloaded"] = True
            self.cache_manager.save_state()
            console.print("[green]Metadata downloaded and extracted.[/green]")
        else:
            console.print("[green]Metadata already present in cache.[/green]")


    def load_index(self):
        """
        Parses the extracted metadata files into an internal index.
        Returns a dictionary with 'arcs' and 'episodes'.
        """
        index = {
            "arcs": [],
            "episodes": {} # mapped by expected filename (without extension)
        }
        
        # The metadata is extracted into a subfolder named "Barry's One Pace Jellyfin Metadata Set/One Pace"
        base_path = next(self.metadata_dir.glob("*/One Pace"), None)
        if not base_path:
            # Fallback to metadata_dir if the structure is different
            base_path = self.metadata_dir / "One Pace"
            
        if not base_path.exists():
            console.print("[red]Metadata structure error: 'One Pace' directory not found.[/red]")
            return index

        # Iterate through arc folders
        for arc_folder in sorted(base_path.iterdir()):
            if arc_folder.is_dir() and arc_folder.name.startswith("[One Pace]"):
                arc_info = {
                    "name": arc_folder.name,
                    "path": arc_folder,
                    "relative_path": arc_folder.relative_to(base_path),
                    "episodes": []
                }
                
                # Each .nfo file (except season.nfo) represents an episode
                for nfo_file in arc_folder.glob("*.nfo"):
                    if nfo_file.name == "season.nfo":
                        continue
                    
                    episode_name = nfo_file.stem
                    arc_info["episodes"].append(episode_name)
                    index["episodes"][episode_name] = {
                        "arc_name": arc_folder.name,
                        "relative_path": arc_folder.relative_to(base_path) / f"{episode_name}.mkv"
                    }
                
                arc_info["episodes"].sort()
                index["arcs"].append(arc_info)
        
        return index
