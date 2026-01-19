# Jellyfin One Pace Downloader

Automated tool to manage and download One Pace episodes from Nyaa.si.

## Features

- **Metadata Management**: Automatically downloads and extracts the latest One Pace metadata for Jellyfin.
- **Scraping**: Scrapes Nyaa.si for the latest One Pace torrents.
- **Analysis**: Analyzes available torrents and compares them with your local metadata to only download required episodes with no duplicates.
- **Download**: Downloads missing episodes automatically using `torrentp`.
- **Disk Space Check**: Verifies available disk space before starting downloads.
- **Caching**: Use a cache to avoid re-doing all the work if you run the program multiple times.

Note: the metadata is the source of truth for the program, the downloaded set is currently managed by Barry from the
official One Pace Discord server.

## Installation

Ensure you have [uv](https://github.com/astral-sh/uv) installed.

```bash
# Clone the repository
git clone https://github.com/PierreLapolla/onepace.git
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

