from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import requests_cache
from bcoding import bdecode
from pedros import get_logger
from pedros import progbar

from config import config


class TorrentAnalyzer:
    def __init__(self):
        self.logger = get_logger()
        self.session = requests_cache.CachedSession(str(config.onepace_folder / config.TORRENT_INFO_CACHE))

    def get_metadata_hashes(self) -> set[str]:
        hashes = set()
        if not config.METADATA_PATH.exists():
            return hashes
        for nfo in config.METADATA_PATH.rglob("*.nfo"):
            match = re.search(r"\[([0-9A-F]{8})\]", nfo.name)
            if match:
                hashes.add(match.group(1).upper())
        return hashes

    def get_torrent_info(self, torrent_url: str) -> dict:
        try:
            resp = self.session.get(torrent_url, timeout=30)
            if resp.status_code != 200:
                return {"files": [], "total_size": 0}
            torrent_data = bdecode(resp.content)
            files = []
            total_size = 0
            if 'info' in torrent_data:
                info = torrent_data['info']
                if 'files' in info:
                    for f in info['files']:
                        files.append("/".join(f['path']))
                        total_size += f.get('length', 0)
                else:
                    files.append(info['name'])
                    total_size = info.get('length', 0)
            return {"files": files, "total_size": total_size}
        except Exception as e:
            self.logger.error(f"Error fetching torrent {torrent_url}: {e}")
            return {"files": [], "total_size": 0}

    def analyze(self, csv_path: Path):
        if not csv_path.exists():
            return

        df = pl.read_csv(csv_path)
        required_hashes = self.get_metadata_hashes()
        self.logger.info(f"Found {len(required_hashes)} required episodes in metadata.")

        torrents_data = []
        hash_to_torrents = {}
        
        for row in progbar(df.iter_rows(named=True), desc="Analyzing torrents", total=len(df), transient=True):
            torrent_url = row.get('torrent')
            if not torrent_url: continue

            info = self.get_torrent_info(torrent_url)
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

        selected_torrents = set()
        for h in required_hashes:
            if h in hash_to_torrents:
                options = hash_to_torrents[h]
                # singles over batches
                best_torrent = min(options, key=lambda x: x['count'])
                best_torrent['download'] = True
                selected_torrents.add(id(best_torrent))

        results = []
        total_download_size = 0
        download_count = 0
        found_hashes = set()
        
        for t in torrents_data:
            if t['download']:
                total_download_size += t['size']
                download_count += 1
                found_hashes.update(t['useful_hashes'])
            
            results.append({
                "name": t['name'],
                "magnet": t['magnet'],
                "torrent": t['torrent'],
                "hashes": t['hashes'],
                "size": t['size'],
                "download": t['download']
            })

        new_df = pl.DataFrame(results)
        new_df.write_csv(csv_path)

        missing = required_hashes - found_hashes
        size_gb = total_download_size / (1024 ** 3)

        self.logger.info(f"Analysis Summary:")
        self.logger.info(f"  - Total episodes required: {len(required_hashes)}")
        self.logger.info(f"  - Episodes found: {len(found_hashes)}/{len(required_hashes)}")
        
        if missing:
            self.logger.warning(f"  - Missing episodes: {len(missing)}")
        else:
            self.logger.info(f"  - All episodes found!")

        self.logger.info(f"  - Torrents selected for download: {download_count}")
        self.logger.info(f"  - Optimized total download size: {size_gb:.2f} GB")
        
        duplicates_count = sum(1 for h, t_list in hash_to_torrents.items() if len(t_list) > 1)
        if duplicates_count:
            self.logger.info(f"  - {duplicates_count} episodes were available in multiple torrents. Individual episodes were prioritized.")
        
        useless_torrents_count = sum(1 for t in torrents_data if not t['useful_hashes'] and t['hashes'])
        if useless_torrents_count:
            self.logger.info(f"  - {useless_torrents_count} torrents were skipped as they don't contain required episodes.")

        self.logger.info(f"  - /{csv_path.name} updated.")
