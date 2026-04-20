# Jonepace

Jonepace downloads the full [One Pace](https://onepace.net/en) library and the official Jellyfin metadata set for use in Jellyfin.

## Warning

`jonepace` downloads the full One Pace library and metadata set.

Before running it, make sure you have at least **400 GB** of free disk space available.

This tool does not define or maintain the metadata itself. Barry's Jellyfin metadata set, maintained by the One Pace
team, is treated as the source of truth for what gets downloaded and how files are organized.

## Requirements

Make sure `uv` is installed and available in your terminal, see [Installing uv](https://docs.astral.sh/uv/getting-started/installation/)

## Run

Use the following command to start the download:

```bash
uvx jonepace
```

After the tool is done, you can copy `Barry's One Pace Jellyfin Metadata Set/One Pace` into your Jellyfin library
location.

## What it does

- Downloads metadata archive from Google Drive
- Extracts metadata into local project directory
- Finds all `magnets.csv` files
- Downloads torrent contents into matching arc folders
- Moves lonely `.mkv` files beside matching `.nfo` files using filename hash
- Removes empty leftover directories after normalization
