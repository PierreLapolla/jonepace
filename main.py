import asyncio
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import gdown
import polars as pl
import torrentp
from pedros import setup_logging, get_logger


@dataclass(frozen=True, slots=True)
class AppConfig:
    here: Path = field(default_factory=lambda: Path.cwd())
    metadata_file_id: str = "1NdEb7X0Rxjp7b_76BH9-TnObTClcASuB"
    metadata_folder_name: str = "Barry's One Pace Jellyfin Metadata Set"
    hash_pattern: re.Pattern[str] = field(
        default_factory=lambda: re.compile(r"\[([0-9A-Fa-f]{8})](?=\.[^.]+$)")
    )

    @property
    def metadata_zip(self) -> Path:
        return self.here / "metadata.zip"

    @property
    def metadata_root(self) -> Path:
        return self.here / self.metadata_folder_name


@dataclass(frozen=True, slots=True)
class MagnetDownload:
    magnet: str
    download_path: Path


setup_logging()
LOGGER = get_logger()
logging.getLogger("torrentp").setLevel(logging.ERROR)
CONFIG = AppConfig()


def download_extract_metadata():
    LOGGER.info(f"Downloading {CONFIG.metadata_file_id}")
    gdown.cached_download(
        url=f"https://drive.google.com/uc?id={CONFIG.metadata_file_id}",
        path=str(CONFIG.metadata_zip),
        postprocess=gdown.extractall,
        quiet=True
    )


def get_magnets() -> list[MagnetDownload]:
    magnet_files = list(CONFIG.metadata_root.rglob("magnets.csv"))

    if not magnet_files:
        raise FileNotFoundError("No magnets file were found")

    scans = [
        pl.scan_csv(
            str(path),
            has_header=False,
            new_columns=["magnet"],
            glob=False,
        )
        .with_columns(
            pl.col("magnet").str.strip_chars().alias("magnet"),
            pl.lit(str(path.parent)).alias("download_path"),
        )
        for path in magnet_files
    ]

    magnets = (
        pl.concat(scans)
        .select(
            pl.col("magnet"),
            pl.col("download_path"),
        )
        .filter(pl.col("magnet") != "")
        .unique(subset=["magnet", "download_path"], maintain_order=True)
        .collect()
        .to_dicts()
    )

    LOGGER.info(f"Found {len(magnets)} magnets")

    return [
        MagnetDownload(
            magnet=entry["magnet"],
            download_path=Path(entry["download_path"]),
        )
        for entry in magnets
    ]


def normalize_downloaded_videos(download_path: Path):
    nfo_paths_by_hash: dict[str, Path] = {}
    for nfo_path in download_path.rglob("*.nfo"):
        match = CONFIG.hash_pattern.search(nfo_path.name)
        if match:
            nfo_paths_by_hash[match.group(1).lower()] = nfo_path

    if not nfo_paths_by_hash:
        return

    for video_path in download_path.rglob("*.mkv"):
        match = CONFIG.hash_pattern.search(video_path.name)
        if not match:
            continue

        nfo_path = nfo_paths_by_hash.get(match.group(1).lower())
        if nfo_path is None:
            continue

        target_path = nfo_path.with_suffix(".mkv")
        if video_path == target_path or target_path.exists():
            continue

        shutil.move(str(video_path), str(target_path))

    for directory in sorted(
            (path for path in download_path.rglob("*") if path.is_dir()),
            reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass


def download_magnets(magnets: list[MagnetDownload]):
    for magnet_download in magnets:
        magnet_download.download_path.mkdir(parents=True, exist_ok=True)

        downloader = torrentp.TorrentDownloader(
            magnet_download.magnet,
            str(magnet_download.download_path),
            stop_after_download=True,
        )
        asyncio.run(downloader.start_download())
        normalize_downloaded_videos(magnet_download.download_path)


def main():
    download_extract_metadata()
    magnets = get_magnets()
    download_magnets(magnets)


if __name__ == "__main__":
    main()
