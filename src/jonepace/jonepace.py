from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

import polars as pl
from jonepace import LOGGER
from jonepace.libtorrent_wrapper import TorrentClient

RELEASES_CSV_URL = "https://raw.githubusercontent.com/PierreLapolla/jonepace/refs/heads/master/releases.csv"


def read_magnet_links(url: str = RELEASES_CSV_URL) -> list[str]:
    with urlopen(url) as response:
        releases = pl.read_csv(
            BytesIO(response.read()),
            schema_overrides={"arc": pl.String, "number": pl.String, "magnet": pl.String},
        )

    magnet_links = (
        releases
        .filter(pl.col("magnet").is_not_null() & (pl.col("magnet").str.strip_chars() != ""))
        .select(pl.col("magnet").str.strip_chars())
        .get_column("magnet")
        .to_list()
    )
    LOGGER.info(f"Found {len(magnet_links)} magnet links in {url}")
    return magnet_links


def main() -> None:
    magnet_links = read_magnet_links()
    #magnet_links = magnet_links[0:10]

    downloads_dir = Path.cwd()

    client = TorrentClient(max_concurrent=5)
    for magnet_link in magnet_links:
        client.add(
            magnet_link=magnet_link,
            destination=downloads_dir,
        )
    LOGGER.info(f"Starting downloads to: {downloads_dir}")
    client.run()
