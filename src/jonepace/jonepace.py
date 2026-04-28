import argparse
from io import StringIO
from pathlib import Path

import pandas as pd
from pedros import get_logger
from jonepace.libtorrent_wrapper import LibtorrentMagnetClient
from jonepace.maintainance import maintain
from jonepace.tui import confirm_download, welcome
from requests import get

LOGGER = get_logger()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="jonepace")
    parser.add_argument(
        "--maintainance",
        action="store_true",
        help="run CSV maintenance tasks instead of the normal application flow",
    )
    return parser.parse_args(argv)


def get_releases() -> pd.DataFrame:
    url = "https://raw.githubusercontent.com/PierreLapolla/jonepace/refs/heads/master/releases.csv"
    response = get(url, timeout=30)
    response.raise_for_status()
    return pd.read_csv(StringIO(response.text))


def cache_path() -> Path:
    return Path.cwd() / "cache.csv"


def _cache_dataframe(releases: pd.DataFrame) -> pd.DataFrame:
    cache = releases.copy()
    cache["downloaded"] = False
    return cache


def _valid_release_rows(releases: pd.DataFrame) -> pd.DataFrame:
    magnet_series = releases["magnet"].fillna("").astype(str).str.strip()
    valid_mask = magnet_series.map(LibtorrentMagnetClient.validate_magnet)
    return releases.loc[valid_mask].copy()


def _magnet_list(dataframe: pd.DataFrame) -> list[str]:
    return dataframe["magnet"].fillna("").astype(str).str.strip().tolist()


def load_or_create_cache(releases: pd.DataFrame) -> pd.DataFrame:
    path = cache_path()
    valid_releases = _valid_release_rows(releases)

    if not path.exists():
        cache = _cache_dataframe(valid_releases)
        cache.to_csv(path, index=False)
        LOGGER.info(f"Created cache at {path}")
        return cache

    cache = pd.read_csv(path)
    cache_magnets = _magnet_list(cache)
    release_magnets = _magnet_list(valid_releases)

    if cache_magnets != release_magnets:
        cache = _cache_dataframe(valid_releases)
        cache.to_csv(path, index=False)
        LOGGER.info(f"Invalidated cache at {path} because release magnets changed")
        return cache

    if "downloaded" not in cache.columns:
        cache["downloaded"] = False
        cache.to_csv(path, index=False)

    cache["downloaded"] = cache["downloaded"].fillna(False).astype(bool)
    return cache


def pending_downloads(cache: pd.DataFrame) -> pd.DataFrame:
    pending = cache.loc[~cache["downloaded"].fillna(False).astype(bool)].copy()
    pending["magnet"] = pending["magnet"].fillna("").astype(str).str.strip()
    return pending.loc[pending["magnet"] != ""]


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.maintainance:
        maintain()
        return

    welcome()
    releases = get_releases()
    cache = load_or_create_cache(releases)
    pending = pending_downloads(cache)
    magnets = pending["magnet"].tolist()
    pending_size = int(pd.to_numeric(pending["size"], errors="coerce").fillna(0).sum())

    LOGGER.info(f"{len(magnets)} downloads pending")
    if not magnets:
        return

    if not confirm_download(pending_size, len(magnets)):
        LOGGER.info("Download cancelled.")
        return


if __name__ == "__main__":
    main()
