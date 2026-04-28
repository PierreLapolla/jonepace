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

## Contributing

Contributions are welcome, especially updates to the torrent list.

If you want to add or fix releases:

1. Fork the repository.
2. Update [releases.csv](releases.csv).
3. Leave the `size` column empty for new or changed rows.
4. Run:

```bash
uv run -m jonepace --maintainance
```

This validates the magnet links and fills the missing sizes.

5. Commit the updated `releases.csv` and open a pull request.
