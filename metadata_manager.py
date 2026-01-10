from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import gdown
from pedros import get_logger

from config import config
from cache_manager import cache


class MetadataManager:
    def __init__(self, onepace_folder: Path):
        self.onepace_folder = onepace_folder
        self.zip_path = onepace_folder / config.METADATA_ZIP
        self.logger = get_logger()

    def download_and_extract_metadata(self):
        extract_path = self.onepace_folder / config.METADATA_ZIP.replace('.zip', '')
        metadata_cache = cache.get("metadata", {})

        if metadata_cache.get("extracted") and extract_path.exists():
            self.logger.info("Metadata already extracted, skipping.")
            return True

        self.logger.info(f"Last updated metadata set is {config.METADATA_SIZE}.")
        if input("Do you want to download and extract metadata now? (y/n): ").lower() != 'y':
            return False

        if not metadata_cache.get("downloaded") or not self.zip_path.exists():
            self.logger.info(f"Downloading metadata to /{self.zip_path.name}...")
            gdown.download(id=config.METADATA_FILE_ID, output=str(self.zip_path), quiet=False)
            metadata_cache["downloaded"] = True
            cache.set("metadata", metadata_cache)

        self.logger.info(f"Extracting /{self.zip_path.name}...")
        with zipfile.ZipFile(self.zip_path, 'r') as zip_ref:
            zip_ref.extractall(self.onepace_folder)

        source_folder = self.onepace_folder / config.METADATA_SOURCE_FOLDER
        if source_folder.exists():
            if extract_path.exists():
                shutil.rmtree(extract_path)
            source_folder.rename(extract_path)

        metadata_cache["extracted"] = True
        cache.set("metadata", metadata_cache)
        self.logger.info("Metadata setup complete.")

        return True
