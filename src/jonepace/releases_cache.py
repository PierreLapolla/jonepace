from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from jonepace import LOGGER

RELEASES_COLUMNS = ("arc", "number", "magnet")
CACHE_COMPLETED_COLUMN = "completed"
RELEASES_SCHEMA = {column: pl.String for column in RELEASES_COLUMNS}
CACHE_SCHEMA = {**RELEASES_SCHEMA, CACHE_COMPLETED_COLUMN: pl.Boolean}


def normalize_releases_frame(releases: pl.DataFrame) -> pl.DataFrame:
    return releases.select(
        pl.col("arc").cast(pl.String).fill_null("").alias("arc"),
        pl.col("number").cast(pl.String).fill_null("").alias("number"),
        pl.col("magnet").cast(pl.String).fill_null("").str.strip_chars().alias("magnet"),
    )


def _normalize_cache_frame(cache: pl.DataFrame) -> pl.DataFrame:
    return cache.select(
        pl.col("arc").cast(pl.String).fill_null("").alias("arc"),
        pl.col("number").cast(pl.String).fill_null("").alias("number"),
        pl.col("magnet").cast(pl.String).fill_null("").str.strip_chars().alias("magnet"),
        pl.col(CACHE_COMPLETED_COLUMN).cast(pl.Boolean, strict=False).fill_null(False).alias(CACHE_COMPLETED_COLUMN),
    )


@dataclass(slots=True)
class ReleaseCache:
    path: Path
    frame: pl.DataFrame

    @classmethod
    def sync(cls, *, downloads_dir: Path, releases: pl.DataFrame) -> ReleaseCache:
        path = downloads_dir / "cache.csv"
        normalized_releases = normalize_releases_frame(releases)
        cached = _read_cache(path)
        frame = _merge_releases_with_cache(releases=normalized_releases, cached=cached)

        cache = cls(path=path, frame=frame)
        if cached is None:
            cache.save()
            LOGGER.info(f"Created download cache at {path}")
            return cache

        cached_releases = cached.select(RELEASES_COLUMNS)
        if not cached_releases.equals(normalized_releases):
            LOGGER.info(f"Detected updates in releases.csv, invalidating stale cache entries in {path}")

        if not cached.equals(frame):
            cache.save()

        return cache

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.frame.write_csv(self.path)

    def pending_magnet_links(self) -> list[str]:
        return (
            self.frame
            .filter(~pl.col(CACHE_COMPLETED_COLUMN) & (pl.col("magnet") != ""))
            .get_column("magnet")
            .to_list()
        )

    def mark_completed(self, magnet_link: str) -> bool:
        normalized_magnet = magnet_link.strip()
        match = self.frame.filter(
            (pl.col("magnet") == normalized_magnet) & ~pl.col(CACHE_COMPLETED_COLUMN),
        )
        if match.is_empty():
            return False

        self.frame = self.frame.with_columns(
            pl.when(pl.col("magnet") == normalized_magnet)
            .then(True)
            .otherwise(pl.col(CACHE_COMPLETED_COLUMN))
            .alias(CACHE_COMPLETED_COLUMN)
        )
        self.save()
        return True


def _merge_releases_with_cache(*, releases: pl.DataFrame, cached: pl.DataFrame | None) -> pl.DataFrame:
    if cached is None:
        return releases.with_columns(pl.lit(False).alias(CACHE_COMPLETED_COLUMN))

    return (
        releases
        .join(
            cached.select(*RELEASES_COLUMNS, CACHE_COMPLETED_COLUMN),
            on=list(RELEASES_COLUMNS),
            how="left",
        )
        .with_columns(pl.col(CACHE_COMPLETED_COLUMN).fill_null(False))
    )


def _read_cache(path: Path) -> pl.DataFrame | None:
    if not path.exists():
        return None

    try:
        cache = pl.read_csv(path, schema_overrides=CACHE_SCHEMA)
    except Exception as exc:
        LOGGER.warning(f"Failed to read existing cache at {path}: {exc}. Rebuilding it.")
        return None

    required_columns = {*RELEASES_COLUMNS, CACHE_COMPLETED_COLUMN}
    if not required_columns.issubset(cache.columns):
        LOGGER.warning(f"Cache at {path} is missing required columns. Rebuilding it.")
        return None

    return _normalize_cache_frame(cache)
