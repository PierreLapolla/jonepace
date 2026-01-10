from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl
from pedros import get_logger, progbar
from torrentp import TorrentDownloader

from config import config
from cache_manager import cache


class DownloadManager:
    def __init__(self):
        self.logger = get_logger()
        config.DOWNLOAD_PATH.mkdir(parents=True, exist_ok=True)

    def check_disk_space(self, required_size: int) -> bool:
        total, used, free = shutil.disk_usage(config.onepace_folder)
        
        self.logger.info(f"Disk Usage Info:")
        self.logger.info(f"  - Total: {total / (1024**3):.2f} GB")
        self.logger.info(f"  - Used:  {used / (1024**3):.2f} GB")
        self.logger.info(f"  - Free:  {free / (1024**3):.2f} GB")
        self.logger.info(f"  - Required for download: {required_size / (1024**3):.2f} GB")

        if free < required_size:
            self.logger.error("Not enough disk space for the selected torrents!")
            return False
            
        confirm = input("\nDo you want to proceed with the download? (y/n): ").lower()
        return confirm == 'y'

    async def download_torrents(self, csv_path: Path):
        if not csv_path.exists():
            return

        df = pl.read_csv(csv_path)
        to_download = df.filter(pl.col("download"))

        arc_order = {tuple(arc) if isinstance(arc, list) else arc: i for i, arc in enumerate(config.ARCS)}

        def get_arc_index(name: str) -> int:
            name_lower = name.lower()
            for arc in config.ARCS:
                if isinstance(arc, list):
                    if any(variation.lower() in name_lower for variation in arc):
                        return arc_order[tuple(arc)]
                else:
                    if arc.lower() in name_lower:
                        return arc_order[arc]
            return len(config.ARCS)

        to_download = to_download.with_columns(
            pl.col("name").map_elements(get_arc_index, return_dtype=pl.Int64).alias("arc_index")
        )
        to_download = to_download.sort("arc_index", "name")

        if len(to_download) == 0:
            self.logger.info("No torrents tagged for download.")
            return

        total_size = to_download["size"].sum()
        
        if not self.check_disk_space(total_size):
            self.logger.info("Download cancelled by user or insufficient space.")
            return

        size_gb = total_size / (1024 ** 3)
        self.logger.info(f"Starting download of {len(to_download)} torrents ({size_gb:.2f} GB)...")

        download_cache = cache.get("downloads", [])

        for row in to_download.iter_rows(named=True):
            name = row['name']
            magnet = row['magnet']
            
            if name in download_cache:
                self.logger.info(f"Skipping {name}, already in cache.")
                continue

            save_path = config.DOWNLOAD_PATH / name
            if save_path.exists():
                self.logger.info(f"Skipping {name}, already exists in downloads.")
                download_cache.append(name)
                cache.set("downloads", download_cache)
                continue

            try:
                downloader = TorrentDownloader(magnet, str(config.DOWNLOAD_PATH))
                await downloader.start_download()
                download_cache.append(name)
                cache.set("downloads", download_cache)
            except Exception as e:
                self.logger.error(f"Failed to download {name}: {e}")

        self.logger.info("All downloads completed.")
