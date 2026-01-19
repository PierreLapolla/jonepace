import asyncio

from pedros import get_logger
from rich.prompt import Confirm

from archive.onepace.core.config import config
from archive.onepace.core.download_manager import DownloadManager
from archive.onepace.core.library_manager import LibraryManager
from archive.onepace.core.metadata_manager import MetadataManager
from archive.onepace.utils.cache import cache
from archive.onepace.utils.system import check_disk_space

logger = get_logger()


def interactive_run():
    """Run the full One Pace setup with interactive prompts."""
    force_metadata = Confirm.ask("Download and extract metadata?")

    scrape = Confirm.ask("Scrape Nyaa.si for torrents?")

    use_cache = True
    if scrape and len(cache) > 0:
        use_cache = Confirm.ask("Use cache for scraping and analysis?")

    asyncio.run(_run(force_metadata, not scrape, use_cache))


async def _run(force_metadata, skip_scrape, use_cache):
    logger.info("One Pace setup starting...")

    # 1. Metadata
    if not MetadataManager(config.onepace_folder).download_and_extract_metadata(force_redownload=force_metadata):
        return

    output_file = config.onepace_folder / config.TORRENTS_CSV

    # 2. Sync & Analyze
    LibraryManager().sync_and_analyze(output_file, skip_scrape=skip_scrape, use_cache=use_cache)

    # 3. Download
    download_manager = DownloadManager()
    required_size = download_manager.get_required_size(output_file, use_cache=use_cache)

    if required_size > 0:
        download_manager.log_disk_usage(required_size)
        if not check_disk_space(config.onepace_folder, required_size):
            logger.error("Aborting due to insufficient disk space.")
            return

    if Confirm.ask("Do you want to proceed with the download?"):
        await download_manager.download_torrents(output_file, use_cache=use_cache)
    else:
        logger.info("Skipping download as requested.")


if __name__ == "__main__":
    interactive_run()
