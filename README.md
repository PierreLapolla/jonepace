# Jellyfin One Pace Downloader

Automated tool to manage and download One Pace episodes from Nyaa.si.

## Features

- **Metadata Management**: Automatically downloads and extracts the latest One Pace metadata for Jellyfin.
- **Scraping**: Scrapes Nyaa.si for the latest One Pace torrents.
- **Analysis**: Analyzes available torrents and compares them with your local metadata to identify missing episodes.
- **Download**: Downloads missing episodes automatically using `torrentp`.
- **Disk Space Check**: Verifies available disk space before starting downloads.
- **Caching**: Efficiently caches scraped data to reduce network requests.

Note: the metadata is the source of truth for the program, the downloaded set is currently managed by Barry from the
official One Pace Discord server.

## Installation

Ensure you have [uv](https://github.com/astral-sh/uv) installed.

```bash
# Clone the repository
git clone <repository-url>
cd onepace

# Install dependencies
uv sync
```

## Usage

Simply run the main script:

```bash
uv run main.py
```

The program will guide you through the process with interactive prompts:

- Confirming if you want to force a metadata update.
- Asking whether to skip scraping if recent data is available.
- Confirming before starting the download of identified torrents.

## Project Structure

- `onepace/core/`: Core logic (Metadata, Scraping, Analysis, Downloading).
- `onepace/cli/`: Interface logic.
- `OnePace/`: Default directory for metadata and downloads (created on first run).

## Requirements

- Python 3.13+
- Dependencies listed in `pyproject.toml`
