import argparse
from pathlib import Path

import polars as pl
from pedros import get_logger
from jonepace.cache import (
    load_or_create_cache,
    pending_downloads,
    prefer_extended_releases,
    regular_releases,
    save_cache,
)
from jonepace.csv_utils import load_csv_text
from jonepace.libtorrent_wrapper import LibtorrentMagnetClient
from jonepace.maintainance import maintain
from jonepace.organizer import organize_files
from jonepace.tui import (
    confirm_download,
    confirm_organize,
    download_progress_sink,
    report_download_results,
    welcome,
)
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
    parser.add_argument(
        "--extended",
        action="store_true",
        help="prefer extended releases when an extended torrent is available",
    )
    parser.add_argument(
        "--rebuild-cache",
        action="store_true",
        help="recreate cache.csv from current release metadata without downloading",
    )
    return parser.parse_args(argv)


def get_releases() -> pl.DataFrame:
    local_path = Path(__file__).parent.parent.with_name("releases.csv")
    if local_path.exists():
        LOGGER.warning(f"Loading releases from {local_path}")
        return load_csv_text(local_path.read_text())

    url = "https://raw.githubusercontent.com/PierreLapolla/jonepace/refs/heads/master/releases.csv"
    response = get(url, timeout=30)
    response.raise_for_status()
    return load_csv_text(response.text)


def maybe_organize_files(root: Path) -> None:
    if confirm_organize():
        organize_files(root)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    args.destination = args.destination.expanduser().resolve()
    if args.maintainance:
        maintain()
        return

    welcome()
    releases = get_releases()
    if args.rebuild_cache:
        save_cache(releases, args.destination)
        return

    selected_releases = prefer_extended_releases(releases) if args.extended else regular_releases(releases)
    cache = load_or_create_cache(releases, args.destination)
    pending = pending_downloads(selected_releases, cache, args.destination)
    magnets = pending.get_column("magnet").to_list()
    pending_sizes = pending.get_column("size").cast(pl.Int64, strict=False).fill_null(0)
    pending_size = int(pending_sizes.sum())
    expected_sizes = {
        magnet.strip(): max(int(size), 0)
        for magnet, size in zip(magnets, pending_sizes.to_list(), strict=False)
        if magnet.strip() and int(size) > 0
    }

    if not magnets:
        save_cache(releases, args.destination)
        maybe_organize_files(args.destination)
        return

    if not confirm_download(pending_size, len(magnets)):
        LOGGER.info("Download cancelled.")
        save_cache(releases, args.destination)
        maybe_organize_files(args.destination)
        return

    with LibtorrentMagnetClient() as client:
        with download_progress_sink("Downloading") as progress_callback:
            results = client.download(
                magnets,
                destination=args.destination,
                download_rate_limit=args.download_rate_limit,
                expected_sizes=expected_sizes,
                progress_callback=progress_callback,
            )

    save_cache(releases, args.destination)
    report_download_results(results, destination=args.destination)
    maybe_organize_files(args.destination)


if __name__ == "__main__":
    main()
