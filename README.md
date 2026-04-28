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

This repo highly encourages contribution to maintain the list of torrent links updated.

- Fork this repo
- Update the [releases file](releases.csv), do not fill the size column
- Run 
```bash 
uv run -m jonepace --maintainance
```
- Create and submit a PR