import json
import os
from pathlib import Path
from platformdirs import user_cache_dir

class CacheManager:
    def __init__(self, app_name="onepace"):
        self.cache_dir = Path(user_cache_dir(app_name))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.cache_dir / "state.json"
        self.metadata_dir = self.cache_dir / "metadata"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.state = self.load_state()

    def load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    return json.load(f)
            except Exception:
                return self.get_default_state()
        return self.get_default_state()

    def get_default_state(self):
        return {
            "paths": {
                "output_dir": ".",
                "existing_downloads_dir": "."
            },
            "metadata": {
                "downloaded": False,
                "local_path": str(self.metadata_dir),
                "fingerprint": None
            },
            "scan": {
                "completed": False,
                "found_episode_ids": []
            },
            "selection": {
                "selected_arc_ids": []
            },
            "downloads": {
                "completed_episode_ids": []
            },
            "build": {
                "completed": False
            }
        }

    def save_state(self):
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=4)

    def clear(self):
        if self.state_file.exists():
            self.state_file.unlink()
        self.state = self.get_default_state()
        # Optionally delete metadata folder contents
        import shutil
        if self.metadata_dir.exists():
            shutil.rmtree(self.metadata_dir)
            self.metadata_dir.mkdir(parents=True, exist_ok=True)
