from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl
from pedros import get_logger, progbar
from torrentp import TorrentDownloader

from onepace.core.config import config
from onepace.utils.cache import cache
from onepace.utils.system import check_disk_space, get_disk_info


class DownloadManager:
    def __init__(self):
        self.logger = get_logger()
        config.DOWNLOAD_PATH.mkdir(parents=True, exist_ok=True)

    def log_disk_usage(self, required_size: int):
        info = get_disk_info(config.onepace_folder)
        self.logger.info(f"Disk Usage Info:")
        self.logger.info(f"  - Total: {info['total'] / (1024**3):.2f} GB")
        self.logger.info(f"  - Used:  {info['used'] / (1024**3):.2f} GB")
        self.logger.info(f"  - Free:  {info['free'] / (1024**3):.2f} GB")
        self.logger.info(f"  - Required for download: {required_size / (1024**3):.2f} GB")

    def get_required_size(self, csv_path: Path) -> int:
        if not csv_path.exists():
            return 0

        df = pl.read_csv(csv_path)
        to_download = df.filter(pl.col("download"))
        return to_download["size"].sum()

    async def download_torrents(self, csv_path: Path, use_cache: bool = True):
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
        
        self.log_disk_usage(total_size)

        size_gb = total_size / (1024 ** 3)
        self.logger.info(f"Starting download of {len(to_download)} torrents ({size_gb:.2f} GB)...")

        download_cache = cache.get("downloads", {})
        if not isinstance(download_cache, dict): # Migration from old list format
            download_cache = {name: "" for name in download_cache}

        for row in to_download.iter_rows(named=True):
            name = row['name']
            magnet = row['magnet']
            
            cached_magnet = download_cache.get(name)
            
            if cached_magnet is not None and use_cache:
                if cached_magnet == magnet:
                    self.logger.info(f"Skipping {name}, already in cache and magnet matches.")
                    continue
                else:
                    self.logger.info(f"Magnet changed for {name}, will re-download.")

            save_path = config.DOWNLOAD_PATH / name
            if save_path.exists() and cached_magnet == magnet and use_cache:
                self.logger.info(f"Skipping {name}, already exists in downloads.")
                download_cache[name] = magnet
                cache.set("downloads", download_cache)
                continue

            try:
                downloader = TorrentDownloader(magnet, str(config.DOWNLOAD_PATH))
                await downloader.start_download()
                download_cache[name] = magnet
                cache.set("downloads", download_cache)
            except Exception as e:
                self.logger.error(f"Failed to download {name}: {e}")

        self.logger.info("All downloads completed.")
