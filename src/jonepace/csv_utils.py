from io import StringIO
from pathlib import Path
from collections.abc import Callable
from typing import Any

import polars as pl

CSV_SCHEMA_OVERRIDES = {
    "arc": pl.String,
    "number": pl.String,
    "magnet": pl.String,
    "file_hashes": pl.String,
}


def load_csv(path: Path) -> pl.DataFrame:
    return pl.read_csv(path, schema_overrides=CSV_SCHEMA_OVERRIDES)


def load_csv_text(text: str) -> pl.DataFrame:
    return pl.read_csv(StringIO(text), schema_overrides=CSV_SCHEMA_OVERRIDES)


def save_csv(path: Path, dataframe: pl.DataFrame) -> None:
    dataframe.write_csv(path)


def ensure_column(
        dataframe: pl.DataFrame,
        column_name: str,
        dtype: pl.DataType,
        *,
        default_value: Any = None,
) -> pl.DataFrame:
    if column_name not in dataframe.columns:
        return dataframe.with_columns(pl.lit(default_value, dtype=dtype).alias(column_name))

    return dataframe.with_columns(pl.col(column_name).cast(dtype, strict=False).alias(column_name))


def add_column(
        dataframe: pl.DataFrame,
        *,
        column_name: str,
        dtype: pl.DataType,
        default_value: Any,
        needs_update: Callable[[object], bool],
        resolve_value: Callable[[dict[str, Any]], tuple[object | None, str | None]],
        on_error: Callable[[int, dict[str, Any], str], None] | None = None,
        on_complete: Callable[[pl.DataFrame], None] | None = None,
) -> pl.DataFrame:
    dataframe = ensure_column(dataframe, column_name, dtype, default_value=default_value)

    values: list[object] = []
    for row_index, row in enumerate(dataframe.iter_rows(named=True)):
        current_value = row.get(column_name)
        if not needs_update(current_value):
            values.append(current_value)
            continue

        value, error = resolve_value(row)
        if value is None:
            if on_error is not None:
                on_error(row_index, row, error or "unknown error")
            values.append(current_value)
            continue

        values.append(value)

    updated = dataframe.with_columns(pl.Series(column_name, values, dtype=dtype))
    if on_complete is not None:
        on_complete(updated)
    return updated
