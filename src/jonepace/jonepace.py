import argparse
from pathlib import Path

import polars as pl
from pedros import get_logger
from jonepace.csv_utils import ensure_column, load_csv, load_csv_text, save_csv
from jonepace.libtorrent_wrapper import LibtorrentMagnetClient
from jonepace.maintainance import maintain
from jonepace.tui import confirm_download, download_progress_sink, report_download_results, welcome
from requests import get

LOGGER = get_logger()
RATE_UNITS = {
    "b": 1,
    "kb": 1000,
    "mb": 1000 ** 2,
    "gb": 1000 ** 3,
}


def parse_rate_limit(value: str) -> int:
    raw = value.strip().lower()
    if not raw:
        raise argparse.ArgumentTypeError("download rate limit cannot be empty")

    if raw == "0":
        return 0

    split_index = next((index for index, char in enumerate(raw) if not (char.isdigit() or char == ".")), len(raw))
    number = raw[:split_index]
    unit = raw[split_index:].strip() or "b"

    if not number:
        raise argparse.ArgumentTypeError(
            "download rate limit must start with a number, for example 20MB"
        )

    try:
        numeric_value = float(number)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "download rate limit must be a number optionally followed by B, KB, MB, or GB"
        ) from exc

    if numeric_value < 0:
        raise argparse.ArgumentTypeError("download rate limit must be non-negative")

    if unit not in RATE_UNITS:
        raise argparse.ArgumentTypeError(
            "download rate limit unit must be one of B, KB, MB, or GB"
        )

    return int(numeric_value * RATE_UNITS[unit])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="jonepace")
    parser.add_argument(
        "--maintainance",
        action="store_true",
        help="run CSV maintenance tasks instead of the normal application flow",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path.cwd(),
        help="directory where torrents will be downloaded (default: current working directory)",
    )
    parser.add_argument(
        "--download-rate-limit",
        type=parse_rate_limit,
        default=0,
        metavar="RATE",
        help="cap aggregate download speed; accepts B, KB, MB, or GB suffixes, 0 disables the limit",
    )
    return parser.parse_args(argv)


def get_releases() -> pl.DataFrame:
    url = "https://raw.githubusercontent.com/PierreLapolla/jonepace/refs/heads/master/releases.csv"
    response = get(url, timeout=30)
    response.raise_for_status()
    return load_csv_text(response.text)


def cache_path() -> Path:
    return Path.cwd() / "cache.csv"


def _cache_dataframe(releases: pl.DataFrame) -> pl.DataFrame:
    return releases.with_columns(pl.lit(False).alias("downloaded"))


def _normalized_magnets(dataframe: pl.DataFrame) -> list[str]:
    return [
        magnet.strip()
        for magnet in dataframe.get_column("magnet").cast(pl.String).fill_null("").to_list()
    ]


def _valid_release_rows(releases: pl.DataFrame) -> pl.DataFrame:
    valid_mask = [LibtorrentMagnetClient.validate_magnet(magnet) for magnet in _normalized_magnets(releases)]
    return releases.filter(pl.Series("valid_magnet", valid_mask))


def load_or_create_cache(releases: pl.DataFrame) -> pl.DataFrame:
    path = cache_path()
    valid_releases = _valid_release_rows(releases)

    if not path.exists():
        cache = _cache_dataframe(valid_releases)
        save_csv(path, cache)
        LOGGER.info(f"Created cache at {path}")
        return cache

    cache = load_csv(path)
    if _normalized_magnets(cache) != _normalized_magnets(valid_releases):
        cache = _cache_dataframe(valid_releases)
        save_csv(path, cache)
        LOGGER.info(f"Invalidated cache at {path} because release magnets changed")
        return cache

    cache = ensure_column(cache, "downloaded", pl.Boolean, default_value=False).with_columns(
        pl.col("downloaded").fill_null(False).cast(pl.Boolean, strict=False).alias("downloaded")
    )
    save_csv(path, cache)
    return cache


def pending_downloads(cache: pl.DataFrame) -> pl.DataFrame:
    normalized = cache.with_columns(
        pl.col("downloaded").fill_null(False).cast(pl.Boolean, strict=False).alias("downloaded"),
        pl.col("magnet").cast(pl.String).fill_null("").str.strip_chars().alias("magnet"),
    )
    return normalized.filter((~pl.col("downloaded")) & (pl.col("magnet") != ""))


def mark_downloaded(cache: pl.DataFrame, completed_magnets: set[str]) -> pl.DataFrame:
    if not completed_magnets:
        return cache

    normalized_magnets = pl.col("magnet").cast(pl.String).fill_null("").str.strip_chars()
    return cache.with_columns(
        pl.when(normalized_magnets.is_in(list(completed_magnets)))
        .then(pl.lit(True))
        .otherwise(pl.col("downloaded").fill_null(False).cast(pl.Boolean, strict=False))
        .alias("downloaded")
    )


def save_cache(cache: pl.DataFrame) -> None:
    path = cache_path()
    save_csv(path, cache)
    LOGGER.info(f"Saved cache to {path}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.maintainance:
        maintain()
        return

    welcome()
    releases = get_releases()
    cache = load_or_create_cache(releases)
    pending = pending_downloads(cache)
    magnets = pending.get_column("magnet").to_list()
    pending_sizes = pending.get_column("size").cast(pl.Int64, strict=False).fill_null(0)
    pending_size = int(pending_sizes.sum())
    expected_sizes = {
        magnet.strip(): max(int(size), 0)
        for magnet, size in zip(magnets, pending_sizes.to_list(), strict=False)
        if magnet.strip() and int(size) > 0
    }

    LOGGER.info(f"{len(magnets)} downloads pending")
    if not magnets:
        return

    if not confirm_download(pending_size, len(magnets)):
        LOGGER.info("Download cancelled.")
        return

    with LibtorrentMagnetClient() as client:
        with download_progress_sink("Downloading One Pace library") as progress_callback:
            results = client.download(
                magnets,
                destination=args.destination,
                download_rate_limit=args.download_rate_limit,
                expected_sizes=expected_sizes,
                progress_callback=progress_callback,
            )

    completed_magnets = {result.magnet for result in results if result.completed}
    updated_cache = mark_downloaded(cache, completed_magnets)
    save_cache(updated_cache)
    report_download_results(results, destination=args.destination)


if __name__ == "__main__":
    main()
