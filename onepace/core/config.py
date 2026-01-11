from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    ONEPACE_FOLDER: Path = Path.cwd() / "OnePace"
    CACHE_PATH: Path = ONEPACE_FOLDER / "app_cache"
    DOWNLOAD_PATH: Path = ONEPACE_FOLDER / "downloads"
    METADATA_PATH: Path = ONEPACE_FOLDER / "metadata" / "One Pace"
    
    METADATA_ZIP: str = "metadata.zip"
    METADATA_FILE_ID: str = "1NdEb7X0Rxjp7b_76BH9-TnObTClcASuB"
    METADATA_SOURCE_FOLDER: str = "Barry's One Pace Jellyfin Metadata Set"
    
    NYAA_BASE_URL: str = "https://nyaa.si"
    NYAA_SEARCH_URL: str = "{base_url}/?f=0&c=0_0&q=one+pace&p={page}"
    TORRENTS_CSV: str = "one_pace_torrents.csv"

    ARCS: list[str | list[str]] = (
        "Romance Dawn",
        "Orange Town",
        "Syrup Village",
        "Gaimon",
        "Baratie",
        "Arlong Park",
        "The Adventures of Buggy's Crew",
        "Loguetown",
        "Reverse Mountain",
        ["Whisky Peak", "Whiskey Peak"],
        "The Trials of Koby-Meppo",
        "Little Garden",
        "Drum Island",
        ["Alabasta", "Arabasta"],
        "Jaya",
        "Skypiea",
        "Long Ring Long Land",
        "Water Seven",
        "Enies Lobby",
        "Post-Enies Lobby",
        "Thriller Bark",
        "Sabaody Archipelago",
        "Amazon Lily",
        "Impel Down",
        "The Adventures of the Straw Hat Pirates",
        "Marineford",
        "Post-War",
        "Return to Sabaody",
        "Fishman Island",
        "Punk Hazard",
        "Dressrosa",
        "Zou",
        "Whole Cake Island",
        "Reverie",
        "Wano",
        "Egghead",
        "Fan Letter",
        "Onigashima Paced",
        "Specials",
    )

    def __post_init__(self):
        self.ONEPACE_FOLDER.mkdir(parents=True, exist_ok=True)

    @property
    def onepace_folder(self) -> Path:
        return self.ONEPACE_FOLDER


config = Config()
