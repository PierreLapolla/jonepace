from pathlib import Path
import json
import re
from typing import Any

import polars as pl
from jonepace.csv_utils import add_column, load_csv, save_csv
from jonepace.libtorrent_wrapper import LibtorrentMagnetClient
from jonepace.tui import metadata_progress_sink
from pedros import get_logger

logger = get_logger()
BYTES_PER_GB = 1000 ** 3
FILE_HASH_PATTERN = re.compile(r"\[([0-9A-Fa-f]{8})](?=\.[^.]+$)")


def validate_magnets(dataframe: pl.DataFrame) -> pl.DataFrame:
    invalid_rows: list[int] = []

    for row_index, row in enumerate(dataframe.iter_rows(named=True)):
        magnet_link = row.get("magnet")
        if magnet_link is not None and LibtorrentMagnetClient.validate_magnet(magnet_link):
            continue

        invalid_rows.append(row_index)
        number = row.get("number") or ""
        if magnet_link is None or not str(magnet_link).strip():
            logger.warning(f"Missing magnet for row {row_index} arc='{row['arc']}' number='{number}'")
        else:
            logger.warning(f"Invalid magnet for row {row_index} arc='{row['arc']}' number='{number}'")

    if invalid_rows:
        raise ValueError(f"Found {len(invalid_rows)} invalid magnet links")

    logger.info("All magnet links are valid")
    return dataframe


def fetch_magnet_metadata(magnets: list[str]) -> dict[str, dict]:
    if not magnets:
        return {}

    with LibtorrentMagnetClient() as client:
        with metadata_progress_sink() as progress_callback:
            metadata_items = client.fetch_metadata(
                magnets,
                max_parallel=300,
                progress_callback=progress_callback,
            )

    return {
        item.magnet: {
            "magnet": item.magnet,
            "info_hash": item.info_hash,
            "name": item.name,
            "total_size": item.total_size,
            "files": item.files,
            "error": item.error,
            "timed_out": item.timed_out,
        }
        for item in metadata_items
    }


def file_hashes_from_metadata_files(files: list[dict[str, Any]] | None) -> list[str] | None:
    if not files:
        return None

    hashes: list[str] = []
    seen: set[str] = set()
    for file_info in files:
        file_path = Path(str(file_info.get("path", ""))).name
        match = FILE_HASH_PATTERN.search(file_path)
        if match is None:
            continue

        file_hash = match.group(1).upper()
        if file_hash in seen:
            continue

        seen.add(file_hash)
        hashes.append(file_hash)

    return hashes or None


def parse_file_hash_list(value: object) -> list[str] | None:
    if value is None:
        return None

    if isinstance(value, list):
        return [str(item).upper() for item in value]

    raw = str(value).strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, list):
        return None

    return [str(item).upper() for item in parsed]


def add_size_column(dataframe: pl.DataFrame, metadata_by_magnet: dict[str, dict]) -> pl.DataFrame:
    def resolve_value(row: dict[str, Any]) -> tuple[object | None, str | None]:
        metadata = metadata_by_magnet.get(str(row["magnet"]).strip())
        if metadata is None:
            return None, "missing metadata"
        if metadata.get("error"):
            return None, str(metadata["error"])
        if metadata.get("total_size") is None:
            return None, "missing total size"
        return int(metadata["total_size"]), None

    def finalize(frame: pl.DataFrame) -> None:
        total_size = int(frame.get_column("size").fill_null(0).sum())
        logger.info(f"Combined size: {total_size} bytes ({total_size / BYTES_PER_GB:.2f} GB)")

    updated = add_column(
        dataframe,
        column_name="size",
        dtype=pl.Int64,
        default_value=None,
        needs_update=lambda value: value is None or int(value) <= 0,
        resolve_value=resolve_value,
        on_error=lambda row_index, row, error: logger.warning(
            f"Could not fill size for row {row_index} arc='{row['arc']}' number='{row.get('number') or ''}': {error}"
        ),
        on_complete=finalize,
    )
    logger.info("Filled size column")
    return updated


def add_file_hashes_column(dataframe: pl.DataFrame, metadata_by_magnet: dict[str, dict]) -> pl.DataFrame:
    def resolve_value(row: dict[str, Any]) -> tuple[object | None, str | None]:
        metadata = metadata_by_magnet.get(str(row["magnet"]).strip())
        if metadata is None:
            return None, "missing metadata"
        if metadata.get("error"):
            return None, str(metadata["error"])

        file_hashes = file_hashes_from_metadata_files(metadata.get("files"))
        if file_hashes is None:
            return None, "could not parse file hashes from torrent filenames"
        return json.dumps(file_hashes), None

    updated = add_column(
        dataframe,
        column_name="file_hashes",
        dtype=pl.String,
        default_value=None,
        needs_update=lambda value: parse_file_hash_list(value) is None,
        resolve_value=resolve_value,
        on_error=lambda row_index, row, error: logger.warning(
            f"Could not fill file_hashes for row {row_index} arc='{row['arc']}' number='{row.get('number') or ''}': {error}"
        ),
    )
    logger.info("Filled file_hashes column")
    return updated


def maintain() -> None:
    csv_path = Path(__file__).parent.parent.with_name("releases.csv")
    dataframe = load_csv(csv_path)
    logger.info(f"Loaded {dataframe.height} rows from {csv_path}")
    dataframe = validate_magnets(dataframe)
    magnets = [
        magnet.strip()
        for magnet in dataframe.get_column("magnet").cast(pl.String).fill_null("").to_list()
        if magnet.strip()
    ]
    logger.info(f"Fetching metadata for {len(magnets)} magnets")
    metadata_by_magnet = fetch_magnet_metadata(magnets)
    dataframe = add_size_column(dataframe, metadata_by_magnet)
    dataframe = add_file_hashes_column(dataframe, metadata_by_magnet)
    save_csv(csv_path, dataframe)
    logger.info(f"Saved csv to {csv_path}")
