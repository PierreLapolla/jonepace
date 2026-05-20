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
RESOLUTION_QUALITY_PATTERN = re.compile(r"(?<!\d)(480|720|1080|2160)p(?!\w)", re.IGNORECASE)
QUALITY_ALIAS_PATTERN = re.compile(r"(?<![A-Za-z0-9])(uhd|full[ ._-]?hd|fhd|hd)(?![A-Za-z0-9])", re.IGNORECASE)
QUALITY_ALIASES = {
    "uhd": "2160p",
    "fullhd": "1080p",
    "fhd": "1080p",
    "hd": "HD",
}
QUALITY_ORDER = {
    "480p": 0,
    "720p": 1,
    "HD": 2,
    "1080p": 3,
    "2160p": 4,
}


def row_magnet(row: dict[str, Any]) -> str:
    return str(row.get("magnet") or "").strip()


def has_magnet(row: dict[str, Any]) -> bool:
    return bool(row_magnet(row))


def is_extended_placeholder(row: dict[str, Any]) -> bool:
    return str(row.get("release_type") or "").strip().lower() == "extended" and not has_magnet(row)


def validate_magnets(dataframe: pl.DataFrame) -> pl.DataFrame:
    invalid_rows: list[int] = []

    for row_index, row in enumerate(dataframe.iter_rows(named=True)):
        if is_extended_placeholder(row):
            continue

        magnet_link = row_magnet(row)
        if LibtorrentMagnetClient.validate_magnet(magnet_link):
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


def qualities_from_names(names: list[str]) -> list[str]:
    qualities: set[str] = set()
    for name in names:
        for match in RESOLUTION_QUALITY_PATTERN.finditer(name):
            qualities.add(f"{match.group(1)}p")

        for match in QUALITY_ALIAS_PATTERN.finditer(name):
            alias = re.sub(r"[ ._-]+", "", match.group(1).lower())
            qualities.add(QUALITY_ALIASES[alias])

    return sorted(qualities, key=lambda quality: QUALITY_ORDER.get(quality, len(QUALITY_ORDER)))


def qualities_from_metadata(metadata: dict[str, Any]) -> list[str] | None:
    names = [str(metadata.get("name") or "")]
    names.extend(str(file_info.get("path") or "") for file_info in metadata.get("files") or [])
    return qualities_from_names(names) or None


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


def parse_quality_list(value: object) -> list[str] | None:
    if value is None:
        return None

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    raw = str(value).strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, list):
        values = [str(item).strip() for item in parsed if str(item).strip()]
        return values or None

    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or None


def add_size_column(dataframe: pl.DataFrame, metadata_by_magnet: dict[str, dict]) -> pl.DataFrame:
    def resolve_value(row: dict[str, Any]) -> tuple[object | None, str | None]:
        if not has_magnet(row):
            return None, None

        metadata = metadata_by_magnet.get(row_magnet(row))
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
        needs_update=lambda value: True,
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
        if not has_magnet(row):
            return None, None

        metadata = metadata_by_magnet.get(row_magnet(row))
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
        needs_update=lambda value: True,
        resolve_value=resolve_value,
        on_error=lambda row_index, row, error: logger.warning(
            f"Could not fill file_hashes for row {row_index} arc='{row['arc']}' number='{row.get('number') or ''}': {error}"
        ),
    )
    logger.info("Filled file_hashes column")
    return updated


def add_quality_column(dataframe: pl.DataFrame, metadata_by_magnet: dict[str, dict]) -> pl.DataFrame:
    def resolve_value(row: dict[str, Any]) -> tuple[object | None, str | None]:
        if not has_magnet(row):
            return None, None

        metadata = metadata_by_magnet.get(row_magnet(row))
        if metadata is None:
            return None, "missing metadata"
        if metadata.get("error"):
            return None, str(metadata["error"])

        qualities = qualities_from_metadata(metadata)
        if qualities is None:
            return None, "could not parse quality from torrent filenames"
        return json.dumps(qualities), None

    updated = add_column(
        dataframe,
        column_name="quality",
        dtype=pl.String,
        default_value=None,
        needs_update=lambda value: True,
        resolve_value=resolve_value,
        on_error=lambda row_index, row, error: logger.warning(
            f"Could not fill quality for row {row_index} arc='{row['arc']}' number='{row.get('number') or ''}': {error}"
        ),
    )
    logger.info("Filled quality column")
    return updated


def maintain() -> None:
    csv_path = Path(__file__).parent.parent.with_name("releases.csv")
    dataframe = load_csv(csv_path)
    logger.info(f"Loaded {dataframe.height} rows from {csv_path}")
    dataframe = validate_magnets(dataframe)
    magnets = [
        raw_magnet.strip()
        for raw_magnet in dataframe.get_column("magnet").cast(pl.String).fill_null("").to_list()
        if raw_magnet.strip()
    ]
    logger.info(f"Fetching metadata for {len(magnets)} magnets")
    metadata_by_magnet = fetch_magnet_metadata(magnets)
    dataframe = add_size_column(dataframe, metadata_by_magnet)
    dataframe = add_file_hashes_column(dataframe, metadata_by_magnet)
    dataframe = add_quality_column(dataframe, metadata_by_magnet)
    save_csv(csv_path, dataframe)
    logger.info(f"Saved csv to {csv_path}")
