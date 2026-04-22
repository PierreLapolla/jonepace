from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TorrentState = Literal["queued", "active", "completed"]


@dataclass(slots=True)
class TorrentTask:
    torrent_id: str
    magnet_link: str
    destination: Path
    name: str
    total_bytes: int = 0
    downloaded_bytes: int = 0
    peers: int = 0
    state: TorrentState = "queued"

    @property
    def completed_bytes(self) -> int:
        return max(0, min(self.downloaded_bytes, self.total_bytes))
