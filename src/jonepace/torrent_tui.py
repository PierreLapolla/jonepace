from __future__ import annotations

from threading import RLock
from types import TracebackType

from rich.live import Live
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from jonepace.torrent_task import TorrentTask


class TorrentProgressTUI:
    """Rich TUI for active torrent downloads."""

    def __init__(
        self,
        *,
        refresh_per_second: int = 12,
        transient: bool = False,
    ) -> None:
        self.refresh_per_second = refresh_per_second
        self.transient = transient

        self._lock = RLock()
        self._task_ids: dict[str, TaskID] = {}
        self._live: Live | None = None

        self._task_progress = Progress(
            TextColumn("{task.fields[filename]}", justify="left"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TextColumn("{task.fields[peers]}", justify="right"),
            TimeRemainingColumn(elapsed_when_finished=True),
        )

    def __enter__(self) -> TorrentProgressTUI:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    def start(self) -> TorrentProgressTUI:
        with self._lock:
            if self._live is not None:
                return self

            self._live = Live(
                self._task_progress,
                refresh_per_second=self.refresh_per_second,
                transient=self.transient,
            )
            self._live.start()
        return self

    def sync(self, task: TorrentTask) -> None:
        with self._lock:
            self._ensure_task_row(task)
            self._sync_task_row(task)
            self._refresh()

    def stop(self) -> None:
        with self._lock:
            if self._live is None:
                return
            self._live.stop()
            self._live = None

    def remove_torrent(self, torrent_id: str) -> None:
        with self._lock:
            task_id = self._task_ids.pop(torrent_id, None)
            if task_id is not None:
                self._task_progress.remove_task(task_id)
            self._refresh()

    def _ensure_task_row(self, task: TorrentTask) -> None:
        if task.state != "active":
            task_id = self._task_ids.pop(task.torrent_id, None)
            if task_id is not None:
                self._task_progress.remove_task(task_id)
            return

        if task.torrent_id not in self._task_ids:
            self._task_ids[task.torrent_id] = self._task_progress.add_task(
                "torrent",
                total=max(task.total_bytes, 1),
                completed=task.completed_bytes,
                filename=self._render_filename(task),
                peers=self._render_peers(task),
            )

    def _sync_task_row(self, task: TorrentTask) -> None:
        task_id = self._task_ids.get(task.torrent_id)
        if task_id is None:
            return

        self._task_progress.update(
            task_id,
            total=max(task.total_bytes, 1),
            completed=task.completed_bytes,
            filename=self._render_filename(task),
            peers=self._render_peers(task),
        )

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.refresh()

    def _render_filename(self, task: TorrentTask) -> str:
        return f"[bold blue]{task.name}[/]"

    def _render_peers(self, task: TorrentTask) -> str:
        return self._format_peers(task.peers)

    def _format_peers(self, peers: int) -> str:
        if peers >= 30:
            color = "green"
        elif peers >= 12:
            color = "yellow"
        else:
            color = "red"
        return f"[{color}]{peers:>2} peers[/]"
