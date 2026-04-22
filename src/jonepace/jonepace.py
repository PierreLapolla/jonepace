from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

import polars as pl
from jonepace import LOGGER
from jonepace.libtorrent_wrapper import TorrentClient
from jonepace.releases_cache import RELEASES_SCHEMA, ReleaseCache

RELEASES_CSV_URL = "https://raw.githubusercontent.com/PierreLapolla/jonepace/refs/heads/master/releases.csv"
DEFAULT_MAX_CONCURRENT = 3


def positive_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 1:
        raise argparse.ArgumentTypeError("max concurrent downloads must be at least 1")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="jonepace",
        description="Download the full One Pace library.",
    )
    parser.add_argument(
        "--max-concurrent",
        type=positive_int,
        default=DEFAULT_MAX_CONCURRENT,
        help=f"maximum number of active torrent downloads (default: {DEFAULT_MAX_CONCURRENT})",
    )
    return parser.parse_args(argv)


def fetch_releases(url: str = RELEASES_CSV_URL) -> pl.DataFrame:
    with urlopen(url) as response:
        return pl.read_csv(
            BytesIO(response.read()),
            schema_overrides=RELEASES_SCHEMA,
        )


def read_magnet_links(url: str = RELEASES_CSV_URL) -> list[str]:
    releases = fetch_releases(url)
    magnet_links = (
        releases
        .filter(pl.col("magnet").is_not_null() & (pl.col("magnet").str.strip_chars() != ""))
        .select(pl.col("magnet").str.strip_chars())
        .get_column("magnet")
        .to_list()
    )
    LOGGER.info(f"Found {len(magnet_links)} magnet links in {url}")
    return magnet_links


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    downloads_dir = Path.cwd()
    releases = fetch_releases()
    cache = ReleaseCache.sync(downloads_dir=downloads_dir, releases=releases)
    magnet_links = cache.pending_magnet_links()

    if not magnet_links:
        LOGGER.info(f"No pending downloads. Cache is up to date at {cache.path}")
        return

    client = TorrentClient(
        max_concurrent=args.max_concurrent,
        on_torrent_completed=lambda task: cache.mark_completed(task.magnet_link),
    )
    for magnet_link in magnet_links:
        client.add(
            magnet_link=magnet_link,
            destination=downloads_dir,
        )
    LOGGER.info(f"Starting {len(magnet_links)} downloads to: {downloads_dir}")
    client.run()
