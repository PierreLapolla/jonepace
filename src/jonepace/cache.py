from pathlib import Path
import json
import re

import polars as pl
from pedros import get_logger

from jonepace.csv_utils import ensure_column, load_csv, save_csv
from jonepace.libtorrent_wrapper import LibtorrentMagnetClient

LOGGER = get_logger()
FILE_HASH_PATTERN = re.compile(r"\[([0-9A-Fa-f]{8})](?=\.[^.]+$)")


def cache_path(root: Path) -> Path:
    return root / "cache.csv"


def release_key(row: dict[str, object]) -> str:
    return f"{release_identity(row)}::{release_type(row)}"


def release_identity(row: dict[str, object]) -> str:
    return f"{row.get('arc') or ''}::{row.get('number') or ''}"


def release_type(row: dict[str, object]) -> str:
    return str(row.get("release_type") or "regular").strip().lower() or "regular"


def parse_file_hash_list(value: object) -> list[str]:
    if value is None:
        return []

    raw = str(value).strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, list):
        return []

    return [str(item).upper() for item in parsed]


def normalized_magnets(dataframe: pl.DataFrame) -> list[str]:
    return [
        magnet.strip()
        for magnet in dataframe.get_column("magnet").cast(pl.String).fill_null("").to_list()
    ]


def valid_release_rows(releases: pl.DataFrame) -> pl.DataFrame:
    valid_mask = [LibtorrentMagnetClient.validate_magnet(magnet) for magnet in normalized_magnets(releases)]
    return releases.filter(pl.Series("valid_magnet", valid_mask))


def regular_releases(releases: pl.DataFrame) -> pl.DataFrame:
    selected_rows = [
        row
        for row in releases.iter_rows(named=True)
        if release_type(row) == "regular"
    ]
    return pl.DataFrame(selected_rows, schema=releases.schema)


def prefer_extended_releases(releases: pl.DataFrame) -> pl.DataFrame:
    valid_releases = valid_release_rows(releases)
    extended_keys = {
        release_identity(row)
        for row in valid_releases.iter_rows(named=True)
        if release_type(row) == "extended"
    }

    if not extended_keys:
        return releases

    selected_rows: list[dict[str, object]] = []
    for row in releases.iter_rows(named=True):
        key = release_identity(row)
        variant = release_type(row)
        if key in extended_keys and variant != "extended":
            LOGGER.info(
                f"Using extended release for arc='{row['arc']}' number='{row.get('number') or ''}'"
            )
            continue

        selected_rows.append(row)

    return pl.DataFrame(selected_rows, schema=releases.schema)


def normalize_cache(dataframe: pl.DataFrame) -> pl.DataFrame:
    dataframe = ensure_column(dataframe, "release_type", pl.String, default_value="regular")
    dataframe = ensure_column(dataframe, "file_hashes", pl.String, default_value=None)
    dataframe = ensure_column(dataframe, "quality", pl.String, default_value=None)
    return dataframe.with_columns(
        pl.col("release_type")
        .fill_null("regular")
        .str.strip_chars()
        .str.to_lowercase()
        .replace("", "regular")
        .alias("release_type")
    )


def load_or_create_cache(releases: pl.DataFrame, root: Path) -> pl.DataFrame:
    path = cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    valid_releases = normalize_cache(valid_release_rows(releases))

    if not path.exists():
        save_csv(path, valid_releases)
        LOGGER.info(f"Created cache at {path}")
        return valid_releases

    cache = normalize_cache(load_csv(path))
    return cache


def save_cache(releases: pl.DataFrame, root: Path) -> None:
    path = cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = normalize_cache(valid_release_rows(releases))
    save_csv(path, snapshot)
    LOGGER.info(f"Saved cache to {path}")


def scan_existing_file_hashes(root: Path) -> dict[str, list[str]]:
    found_hashes: dict[str, list[str]] = {}

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".mkv":
            continue

        match = FILE_HASH_PATTERN.search(path.name)
        if match is None:
            continue

        file_hash = match.group(1).upper()
        found_hashes.setdefault(file_hash, []).append(str(path.relative_to(root)))

    LOGGER.info(f"Scanned {root} and found {len(found_hashes)} unique episode hashes")
    return found_hashes


def pending_downloads(releases: pl.DataFrame, cache: pl.DataFrame, root: Path) -> pl.DataFrame:
    valid_releases = valid_release_rows(releases)
    installed_hashes = scan_existing_file_hashes(root)
    cached_hashes_by_release = {
        release_key(row): parse_file_hash_list(row.get("file_hashes"))
        for row in normalize_cache(cache).iter_rows(named=True)
    }

    pending_rows: list[dict[str, object]] = []
    for row in valid_releases.iter_rows(named=True):
        key = release_key(row)
        current_hashes = parse_file_hash_list(row.get("file_hashes"))
        previous_hashes = cached_hashes_by_release.get(key, [])
        missing_hashes = [file_hash for file_hash in current_hashes if file_hash not in installed_hashes]

        if previous_hashes and previous_hashes != current_hashes:
            LOGGER.info(
                f"Release updated for arc='{row['arc']}' number='{row.get('number') or ''}': "
                f"cache={previous_hashes} releases={current_hashes}"
            )

        if missing_hashes:
            LOGGER.info(
                f"Missing episode for arc='{row['arc']}' number='{row.get('number') or ''}': {missing_hashes}"
            )
            pending_rows.append(row)
            continue

        if previous_hashes and previous_hashes != current_hashes:
            LOGGER.info(
                f"Updated release already present for arc='{row['arc']}' number='{row.get('number') or ''}'"
            )

    if not pending_rows:
        return valid_releases.head(0)

    return pl.DataFrame(pending_rows, schema=valid_releases.schema)
