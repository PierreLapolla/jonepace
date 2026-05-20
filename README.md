![PyPI - Version](https://img.shields.io/pypi/v/jonepace)


# Jonepace

Jonepace downloads the full [One Pace](https://onepace.net/en) library for use in Jellyfin.

## Warning

`jonepace` downloads the full One Pace library.

Before running it, make sure you have at least **300 GB** of free disk space available.

## Requirements

Make sure `uv` is installed and available in your terminal, see [Installing uv](https://docs.astral.sh/uv/getting-started/installation/)

## Run

Use the following command to start the download:

```bash
uvx jonepace
```

When running from a local checkout during development, use:

```bash
uv run jonepace
```

## Arguments

`jonepace` supports the following CLI arguments:

| Argument | Description |
| --- | --- |
| `--destination PATH` | Directory where torrents will be downloaded. Default: current working directory. |
| `--download-rate-limit RATE` | Cap aggregate download bandwidth. Accepts `B`, `KB`, `MB`, or `GB` suffixes such as `500KB`, `20MB`, or `1.5GB`. Use `0` for unlimited. Default: `0`. |
| `--extended` | Prefer extended releases when an extended torrent is available. |
| `--rebuild-cache` | Recreate `cache.csv` from current release metadata without downloading. |
| `--maintainance` | Run CSV maintenance tasks instead of downloading the library. |

## Examples

Download into a specific media folder:

```bash
uvx jonepace --destination "/srv/media/One Pace"
```

Limit total download bandwidth to 20 MB/s:

```bash
uvx jonepace --download-rate-limit 20MB
```

Use both options together:

```bash
uvx jonepace --destination "/srv/media/One Pace" --download-rate-limit 8MB
```

Prefer extended releases when available:

```bash
uvx jonepace --extended
```

Rebuild the local cache metadata without downloading:

```bash
uvx jonepace --destination "/srv/media/One Pace" --rebuild-cache
```

## Contributing

Contributions are welcome, especially updates to the torrent list.

If you want to add or fix releases:

1. Fork the repository.
2. Add or update rows in [releases.csv](releases.csv): fill `arc`, `number`, `magnet`, and `release_type` (`regular` or `extended`); leave `size`, `file_hashes`, and `quality` empty.
3. Run:

```bash
uv run -m jonepace --maintainance
```

This validates the magnet links and refreshes the `size`, `file_hashes`, and `quality` values.

4. Commit the updated `releases.csv` and open a pull request.
