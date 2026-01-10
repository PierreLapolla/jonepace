from __future__ import annotations

from pedros import get_logger
import asyncio

from config import config
from metadata_manager import MetadataManager
from nyaa_scraper import NyaaScraper
from torrent_manager import TorrentAnalyzer
from download_manager import DownloadManager

logger = get_logger()


async def main():
    logger.info("OnePace setup starting...")

    if not MetadataManager(config.onepace_folder).download_and_extract_metadata():
        exit(0)

    output_file = config.onepace_folder / config.TORRENTS_CSV
    NyaaScraper().run(output_file)

    TorrentAnalyzer().analyze(output_file)
    await DownloadManager().download_torrents(output_file)


if __name__ == "__main__":
    asyncio.run(main())
