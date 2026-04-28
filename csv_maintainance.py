from pathlib import Path

import pandas as pd
from jonepace.libtorrent_wrapper import LibtorrentMagnetClient
from jonepace.tui import metadata_progress_sink
from pedros import get_logger

logger = get_logger()


def load_csv(path: Path) -> pd.DataFrame:
    dataframe = pd.read_csv(path)
    logger.info(f"Loaded {len(dataframe)} rows from {path}")
    return dataframe


def validate_magnets(dataframe: pd.DataFrame) -> pd.DataFrame:
    invalid_rows: list[int] = []

    for row_index, row in dataframe.iterrows():
        magnet_link = row["magnet"]
        if not pd.isna(magnet_link) and LibtorrentMagnetClient.validate_magnet(magnet_link):
            continue

        invalid_rows.append(row_index)
        number = row["number"] if pd.notna(row["number"]) else ""
        if pd.isna(magnet_link) or not str(magnet_link).strip():
            logger.warning(f"Missing magnet for row {row_index} arc='{row['arc']}' number='{number}'")
        else:
            logger.warning(f"Invalid magnet for row {row_index} arc='{row['arc']}' number='{number}'")

    if invalid_rows:
        raise ValueError(f"Found {len(invalid_rows)} invalid magnet links")

    logger.info("All magnet links are valid")
    return dataframe


def fetch_magnet_metadata(magnets: list[str]) -> dict[str, dict]:
    with LibtorrentMagnetClient() as client:
        with metadata_progress_sink("Fetching release metadata") as progress_callback:
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


def add_size_column(dataframe: pd.DataFrame) -> pd.DataFrame:
    def log_total_size() -> None:
        total_size = int(dataframe["size"].fillna(0).sum())
        logger.info(f"Combined size: {total_size} bytes ({total_size / 1024**3:.2f} GiB)")

    if "size" not in dataframe.columns:
        dataframe["size"] = pd.Series([pd.NA] * len(dataframe), dtype="Int64")
    else:
        dataframe["size"] = pd.to_numeric(dataframe["size"], errors="coerce").astype("Int64")

    missing_size_mask = dataframe["size"].isna() | dataframe["size"].le(0)
    magnets = dataframe.loc[missing_size_mask, "magnet"].astype(str).tolist()
    if not magnets:
        log_total_size()
        logger.info("All sizes already filled")
        return dataframe

    logger.info(f"Fetching sizes for {len(magnets)} magnet links")
    metadata_by_magnet = fetch_magnet_metadata(magnets)

    for row_index in dataframe.index[missing_size_mask]:
        magnet = str(dataframe.at[row_index, "magnet"])
        metadata = metadata_by_magnet.get(magnet)

        if metadata is None or metadata.get("error") or metadata.get("total_size") is None:
            row = dataframe.loc[row_index]
            number = row["number"] if pd.notna(row["number"]) else ""
            error = metadata["error"] if metadata is not None else "missing metadata"
            logger.warning(f"Could not fetch size for row {row_index} arc='{row['arc']}' number='{number}': {error}")
            continue

        dataframe.at[row_index, "size"] = int(metadata["total_size"])

    log_total_size()
    logger.info("Filled size column")
    return dataframe


def save_csv(path: Path, dataframe: pd.DataFrame) -> None:
    dataframe.to_csv(path, index=False)
    logger.info(f"Saved csv to {path}")


def main() -> None:
    csv_path = Path(__file__).with_name("releases.csv")
    dataframe = load_csv(csv_path)
    dataframe = validate_magnets(dataframe)
    dataframe = add_size_column(dataframe)
    save_csv(csv_path, dataframe)


if __name__ == "__main__":
    main()
