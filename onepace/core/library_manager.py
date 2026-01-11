from __future__ import annotations

import re
import time
from pathlib import Path

import polars as pl
import requests
from bs4 import BeautifulSoup
from bcoding import bdecode
from pedros import get_logger, progbar

from onepace.utils.cache import cache
from onepace.core.config import config


class LibraryManager:
    def __init__(self):
        self.logger = get_logger()

    def _fetch_page(self, url: str, use_cache: bool = True) -> bytes | None:
        cache_key = f"nyaa_page_{url}"
        if use_cache:
            cached = cache.get(cache_key)
            if cached:
                return cached

        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            cache.set(cache_key, resp.content, expire=3600 * 24)
            return resp.content
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return None

    def scrape_nyaa(self, query: str = "one pace", use_cache: bool = True) -> pl.DataFrame:
        results = []
        page = 1
        total_expected = None
        pbar = None

        while True:
            url = f"{config.NYAA_BASE_URL}/?f=0&c=0_0&q={query.replace(' ', '+')}&p={page}"
            content = self._fetch_page(url, use_cache=use_cache)
            if not content:
                break

            soup = BeautifulSoup(content, 'html.parser')

            if total_expected is None:
                info_div = soup.find('div', class_='pagination-page-info')
                if info_div:
                    match = re.search(r'out of (\d+) results', info_div.text)
                    if match:
                        total_expected = int(match.group(1))
                        total_pages = (total_expected + 74) // 75
                        pbar = progbar(range(total_pages), desc=f"Scraping Nyaa", transient=True)
                        next(pbar, None)
            elif pbar:
                next(pbar, None)

            rows = soup.select('tr.default, tr.success, tr.danger, tr.info')
            if not rows:
                break

            for row in rows:
                title_link = row.find('a', href=lambda x: x and x.startswith('/view/') and '#comments' not in x)
                if not title_link or not title_link.get('title'):
                    links = row.find_all('a', href=lambda x: x and x.startswith('/view/') and '#comments' not in x)
                    for link in links:
                        if link.get('title'):
                            title_link = link
                            break
                if not title_link:
                    continue

                magnet = row.find('a', href=lambda x: x and x.startswith('magnet:'))
                torrent = row.find('a', href=lambda x: x and x.endswith('.torrent'))
                if not magnet or not torrent:
                    continue

                results.append({
                    'name': title_link['title'],
                    'magnet': magnet['href'],
                    'torrent': config.NYAA_BASE_URL + torrent['href']
                })

            if not soup.find('li', class_='next'):
                break
            page += 1
            if not use_cache:
                time.sleep(0.5)

        df = pl.DataFrame(results).unique(subset=['magnet'])
        self.logger.info(f"Scraped {len(df)} unique items from Nyaa.")
        return df

    def get_torrent_info(self, torrent_url: str, use_cache: bool = True) -> dict:
        cache_key = f"torrent_info_{torrent_url}"
        if use_cache:
            cached = cache.get(cache_key)
            if cached:
                return cached

        content = self._fetch_page(torrent_url, use_cache=use_cache)
        if not content:
            return {"files": [], "total_size": 0}

        try:
            torrent_data = bdecode(content)
            files = []
            total_size = 0
            info = torrent_data.get('info', {})
            if 'files' in info:
                for f in info['files']:
                    files.append("/".join(f['path']))
                    total_size += f.get('length', 0)
            else:
                files.append(info.get('name', ''))
                total_size = info.get('length', 0)
            
            result = {"files": files, "total_size": total_size}
            cache.set(cache_key, result)
            return result
        except Exception as e:
            self.logger.error(f"Error decoding torrent {torrent_url}: {e}")
            return {"files": [], "total_size": 0}

    def get_metadata_hashes(self) -> set[str]:
        hashes = set()
        if not config.METADATA_PATH.exists():
            return hashes
        for nfo in config.METADATA_PATH.rglob("*.nfo"):
            match = re.search(r"\[([0-9A-F]{8})\]", nfo.name)
            if match:
                hashes.add(match.group(1).upper())
        return hashes

    def sync_and_analyze(self, csv_path: Path, skip_scrape: bool = False, use_cache: bool = True):
        if skip_scrape and csv_path.exists():
            df = pl.read_csv(csv_path)
        else:
            df = self.scrape_nyaa(use_cache=use_cache)
        
        required_hashes = self.get_metadata_hashes()
        self.logger.info(f"Metadata check: {len(required_hashes)} episodes required.")

        torrents_data = []
        hash_to_torrents = {}

        for row in progbar(df.iter_rows(named=True), desc="Analyzing torrents", total=len(df), transient=True):
            torrent_url = row.get('torrent')
            if not torrent_url:
                continue

            info = self.get_torrent_info(torrent_url, use_cache=use_cache)
            torrent_hashes = []
            for f in info['files']:
                match = re.search(r"\[([0-9A-F]{8})\]", f, re.IGNORECASE)
                if match:
                    h = match.group(1).upper()
                    torrent_hashes.append(h)
            
            useful_hashes = [h for h in torrent_hashes if h in required_hashes]
            
            t_info = {
                "name": row['name'],
                "magnet": row['magnet'],
                "torrent": row['torrent'],
                "hashes": "|".join(torrent_hashes),
                "useful_hashes": useful_hashes,
                "size": info['total_size'],
                "count": len(torrent_hashes),
                "download": False
            }
            torrents_data.append(t_info)
            
            for h in useful_hashes:
                if h not in hash_to_torrents:
                    hash_to_torrents[h] = []
                hash_to_torrents[h].append(t_info)

        # Selection logic: prioritize torrents with fewer files (singles over batches) for the same hash
        found_hashes = set()
        for h in required_hashes:
            if h in hash_to_torrents:
                best_torrent = min(hash_to_torrents[h], key=lambda x: x['count'])
                best_torrent['download'] = True
                found_hashes.add(h)

        results = []
        total_download_size = 0
        download_count = 0
        
        for t in torrents_data:
            if t['download']:
                total_download_size += t['size']
                download_count += 1
            
            results.append({
                "name": t['name'],
                "magnet": t['magnet'],
                "torrent": t['torrent'],
                "hashes": t['hashes'],
                "size": t['size'],
                "download": t['download']
            })

        pl.DataFrame(results).write_csv(csv_path)
        
        missing = required_hashes - found_hashes
        self.logger.info(f"Analysis complete: {len(found_hashes)}/{len(required_hashes)} episodes found.")
        if missing:
            self.logger.warning(f"{len(missing)} episodes missing from available torrents.")
        self.logger.info(f"Selected {download_count} torrents totaling {total_download_size / (1024**3):.2f} GB.")
