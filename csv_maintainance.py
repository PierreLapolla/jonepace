from datetime import datetime
from pathlib import Path
from shutil import copy2
from urllib.parse import parse_qs, urlencode, urlsplit

import polars as pl
from pedros import get_logger

logger = get_logger()
CSV_PATH = Path(__file__).with_name("releases.csv")
BACKUPS_DIR = Path(__file__).with_name("backups")
CSV_SCHEMA = {"arc": pl.String, "number": pl.String, "magnet": pl.String}


def _number_label(number: str | None) -> str:
    return "null" if number in (None, "") else number


def simplify_magnet_link(magnet_link: str | None) -> str | None:
    if magnet_link is None:
        return None

    stripped = magnet_link.strip()
    if not stripped:
        return ""

    query = parse_qs(urlsplit(stripped).query, keep_blank_values=False)
    xt_values = query.get("xt", [])
    if not xt_values:
        return stripped

    params: list[tuple[str, str]] = [("xt", xt_values[0])]
    dn_values = query.get("dn", [])
    if dn_values:
        params.append(("dn", dn_values[0]))

    return f"magnet:?{urlencode(params)}"


def simplify_magnets(releases: pl.DataFrame) -> pl.DataFrame:
    simplified = releases.with_columns(
        pl.col("magnet").map_elements(simplify_magnet_link, return_dtype=pl.String).alias("magnet")
    )
    simplified_count = 0

    for before_row, after_row in zip(
        releases.select("arc", "number", "magnet").iter_rows(named=True),
        simplified.select("magnet").iter_rows(named=True),
        strict=True,
    ):
        if before_row["magnet"] == after_row["magnet"]:
            continue

        simplified_count += 1
        location = f"{before_row['arc']}:{_number_label(before_row['number'])}"
        logger.info(
            f"Simplified magnet for {location}: "
            f"{before_row['magnet']} -> {after_row['magnet']}"
        )

    logger.info(f"Simplified {simplified_count} magnet links")
    return simplified


def check_duplicates_magnets(releases: pl.DataFrame) -> None:
    normalized_releases = releases.with_columns(
        [
            pl.col("magnet").str.strip_chars().alias("magnet"),
            pl.when(pl.col("number").is_null() | (pl.col("number") == ""))
            .then(pl.lit("null"))
            .otherwise(pl.col("number"))
            .alias("_number_label"),
        ]
    )

    duplicate_magnets = (
        normalized_releases
        .filter(pl.col("magnet").is_not_null() & (pl.col("magnet") != ""))
        .group_by("magnet")
        .agg(
            [
                pl.len().alias("count"),
                pl.format("{}:{}", pl.col("arc"), pl.col("_number_label"))
                .sort()
                .alias("locations"),
            ]
        )
        .filter(pl.col("count") > 1)
        .sort(["count", "magnet"], descending=[True, False])
    )

    has_duplicates = duplicate_magnets.height > 0

    if not has_duplicates:
        logger.info(f"No duplicate magnets found at {CSV_PATH.name}")
        return

    for duplicate in duplicate_magnets.iter_rows(named=True):
        locations = ", ".join(duplicate["locations"])
        logger.error(f"Duplicate magnet link found {duplicate['count']} times at {locations}")


def save_csv_maintenance_backup(csv_path: Path = CSV_PATH, backups_dir: Path = BACKUPS_DIR) -> Path:
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backups_dir / f"{csv_path.stem}_maintenance_backup_{timestamp}{csv_path.suffix}"
    copy2(csv_path, backup_path)
    logger.info(f"Saved CSV backup to {backup_path}")
    return backup_path


def main():
    releases = pl.read_csv(CSV_PATH, schema_overrides=CSV_SCHEMA)
    releases = simplify_magnets(releases)
    releases.write_csv(CSV_PATH, null_value="")
    check_duplicates_magnets(releases)
    save_csv_maintenance_backup()


if __name__ == "__main__":
    main()
