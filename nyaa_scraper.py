from __future__ import annotations

import re
import time
from pathlib import Path

import polars as pl
from bs4 import BeautifulSoup
from pedros import get_logger, progbar

from config import config
from cache_manager import cache


class NyaaScraper:
    def __init__(self):
        self.logger = get_logger()

    def scrape_all_pages(self, query: str = "one pace"):
        results = []
        page = 1
        total_expected = None
        
        pbar = None
        while True:
            url = f"{config.NYAA_BASE_URL}/?f=0&c=0_0&q={query.replace(' ', '+')}&p={page}"
            
            cache_key = f"nyaa_scrape_{url}"
            cached_resp = cache.get(cache_key)
            
            if cached_resp:
                content, from_cache = cached_resp, True
            else:
                import requests
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                content, from_cache = resp.content, False
                cache.set(cache_key, content, expire=3600 * 24)

            soup = BeautifulSoup(content, 'html.parser')

            if total_expected is None:
                info_div = soup.find('div', class_='pagination-page-info')
                if info_div:
                    match = re.search(r'out of (\d+) results', info_div.text)
                    if match:
                        total_expected = int(match.group(1))
                        # Estimate number of pages (75 results per page)
                        total_pages = (total_expected + 74) // 75
                        pbar = progbar(range(total_pages), desc=f"Scraping '{query}'", transient=True)
                        next(pbar, None)
            elif pbar:
                next(pbar, None)

            rows = soup.select('tr.default, tr.success, tr.danger, tr.info')
            if not rows: break

            for row in rows:
                title_link = row.find('a', href=lambda x: x and x.startswith('/view/') and '#comments' not in x)
                if not title_link or not title_link.get('title'):
                    links = row.find_all('a', href=lambda x: x and x.startswith('/view/') and '#comments' not in x)
                    for link in links:
                        if link.get('title'):
                            title_link = link
                            break

                if not title_link: continue

                magnet = row.find('a', href=lambda x: x and x.startswith('magnet:'))
                torrent = row.find('a', href=lambda x: x and x.endswith('.torrent'))
                if not magnet or not torrent: continue

                results.append({
                    'name': title_link['title'],
                    'magnet': magnet['href'],
                    'torrent': config.NYAA_BASE_URL + torrent['href']
                })

            if not soup.find('li', class_='next'): break
            page += 1
            if not from_cache:
                time.sleep(0.5)

        return results, total_expected

    def run(self, output_path: Path):
        data, total_expected = self.scrape_all_pages()
        if not data: return

        df = pl.DataFrame(data)
        initial_count = len(df)
        df = df.unique(subset=['magnet'])

        self.logger.info(f"Scraped {initial_count} items.")
        if total_expected:
            self.logger.info(f"Site reported {total_expected} results. We got {initial_count} ({len(df)} unique).")

        df.write_csv(output_path)
        self.logger.info(f"Saved to /{output_path.name}")
