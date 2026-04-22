# Jonepace

Jonepace downloads the full [One Pace](https://onepace.net/en) library for use in Jellyfin.

## Warning

`jonepace` downloads the full One Pace library.

Before running it, make sure you have at least **400 GB** of free disk space available.

## Requirements

Make sure `uv` is installed and available in your terminal, see [Installing uv](https://docs.astral.sh/uv/getting-started/installation/)

## Run

Use the following command to start the download:

```bash
uvx jonepace
```

The downloader creates a `cache.csv` file in the download directory. It mirrors `releases.csv` with an extra `completed` column so completed torrents are skipped on later runs, and changed release entries are invalidated and queued again automatically.

You can override the number of simultaneous downloads with `--max-concurrent`:

```bash
uvx jonepace --max-concurrent 5
```
