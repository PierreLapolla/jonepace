from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import re
from time import sleep
from urllib.parse import parse_qs, unquote_plus, urlsplit

import libtorrent as lt

from jonepace import LOGGER
from jonepace.torrent_task import TorrentTask
from jonepace.torrent_tui import TorrentProgressTUI


class TorrentClient:
    """Small libtorrent wrapper with queueing and Rich TUI updates."""

    def __init__(
        self,
        *,
        max_concurrent: int = 5,
        poll_interval: float = 0.5,
        refresh_per_second: int = 12,
        listen_interfaces: str = "0.0.0.0:6881",
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than 0")

        self.max_concurrent = max_concurrent
        self.poll_interval = poll_interval
        self.listen_interfaces = listen_interfaces

        self._session: lt.session | None = None
        self._tui = TorrentProgressTUI(
            refresh_per_second=refresh_per_second,
        )
        self._tasks: list[TorrentTask] = []
        self._task_index: dict[str, TorrentTask] = {}
        self._handles: dict[str, lt.torrent_handle] = {}
        self._active_ids: set[str] = set()
        self._seen_tracker_alerts: set[str] = set()

    def add(self, *, magnet_link: str, destination: str | Path) -> str:
        torrent_id, name = self._parse_magnet_link(magnet_link)
        if torrent_id in self._task_index:
            raise ValueError(f"Torrent already queued: {torrent_id}")

        torrent = TorrentTask(
            torrent_id=torrent_id,
            magnet_link=magnet_link.strip(),
            destination=Path(destination).expanduser(),
            name=name,
        )
        self._tasks.append(torrent)
        self._task_index[torrent_id] = torrent
        return torrent_id

    def extend(self, magnet_links: Iterable[str], *, destination: str | Path) -> None:
        for magnet_link in magnet_links:
            self.add(magnet_link=magnet_link, destination=destination)

    def run(self) -> None:
        if not self._tasks:
            LOGGER.warning("No torrents queued.")
            return

        session = self._ensure_session()

        try:
            with self._tui:
                self._attach_torrents(session)
                self._resume_waiting_torrents()
                while not self._all_completed():
                    session.post_torrent_updates()
                    sleep(self.poll_interval)
                    self._drain_alerts()
                    self._resume_waiting_torrents()
        finally:
            session.pause()

    def _ensure_session(self) -> lt.session:
        if self._session is None:
            self._session = lt.session(
                {
                    "listen_interfaces": self.listen_interfaces,
                    "alert_mask": int(
                        lt.alert.category_t.error_notification
                        | lt.alert.category_t.status_notification
                        | lt.alert.category_t.storage_notification
                    ),
                }
            )
            self._session.apply_settings(
                {
                    "alert_queue_size": 10000,
                    "active_limit": self.max_concurrent,
                    "active_downloads": self.max_concurrent,
                    "active_seeds": 0,
                }
            )
            self._session.set_download_rate_limit(0)
            self._session.set_upload_rate_limit(0)
            self._session.set_local_download_rate_limit(0)
            self._session.set_local_upload_rate_limit(0)
            self._session.set_max_connections(0)
            self._session.set_max_half_open_connections(0)
            self._start_network_services(self._session)
        return self._session

    def _attach_torrents(self, session: lt.session) -> None:
        for torrent in self._tasks:
            if torrent.torrent_id in self._handles:
                continue

            torrent.destination.mkdir(parents=True, exist_ok=True)
            params = lt.parse_magnet_uri(torrent.magnet_link)
            params.save_path = str(torrent.destination)
            params.flags |= lt.torrent_flags.paused
            params.flags |= lt.torrent_flags.duplicate_is_error
            params.flags &= ~lt.torrent_flags.auto_managed
            self._handles[torrent.torrent_id] = session.add_torrent(params)

    def _resume_waiting_torrents(self) -> None:
        active_count = sum(
            1
            for torrent in self._tasks
            if torrent.state == "active"
        )
        if active_count >= self.max_concurrent:
            return

        for torrent in self._tasks:
            if active_count >= self.max_concurrent:
                break
            if torrent.state != "queued":
                continue

            handle = self._handles.get(torrent.torrent_id)
            if handle is None or not handle.is_valid():
                continue

            self._active_ids.add(torrent.torrent_id)
            torrent.state = "active"
            handle.resume()
            active_count += 1
            self._tui.sync(torrent)
            # LOGGER.info("Resumed torrent: %s", torrent.name)

    def _drain_alerts(self) -> None:
        session = self._session
        if session is None:
            return

        for alert in session.pop_alerts():
            if isinstance(alert, lt.state_update_alert):
                self._handle_state_update(alert)
                continue

            if isinstance(alert, lt.add_torrent_alert) and alert.error.value() != 0:
                LOGGER.error(alert.message())
                continue

            if isinstance(alert, (lt.tracker_error_alert, lt.tracker_warning_alert)):
                self._log_tracker_alert(alert)
                continue

            alert_name = type(alert).__name__.lower()
            if "error" in alert_name or "fail" in alert_name:
                LOGGER.error(alert.message())

    def _all_completed(self) -> bool:
        return all(torrent.state == "completed" for torrent in self._tasks)

    def _handle_state_update(self, alert: lt.state_update_alert) -> None:
        for status in alert.status:
            torrent_id = self._resolve_torrent_id(status)
            task = self._task_index.get(torrent_id)
            if task is None:
                continue

            was_completed = task.state == "completed"
            self._update_task_from_status(task, status)
            self._tui.sync(task)

            if not was_completed and task.state == "completed":
                self._active_ids.discard(task.torrent_id)
                handle = self._handles.get(task.torrent_id)
                if handle is not None and handle.is_valid():
                    handle.pause()
                    session = self._session
                    if session is not None:
                        session.remove_torrent(handle)
                self._handles.pop(task.torrent_id, None)
                # LOGGER.info("Completed torrent: %s", task.name)

    def _update_task_from_status(self, task: TorrentTask, status: lt.torrent_status) -> None:
        task.name = str(status.name or task.name)
        task.total_bytes = max(int(status.total_wanted), 0)
        task.downloaded_bytes = max(int(status.total_wanted_done), 0)
        task.peers = max(int(status.num_peers), 0)

        if self._is_finished(status):
            task.state = "completed"
            self._active_ids.discard(task.torrent_id)
        elif task.torrent_id in self._active_ids:
            task.state = "active"
        else:
            task.state = "queued"

    def _is_finished(self, status: lt.torrent_status) -> bool:
        if bool(status.is_seeding) or bool(status.is_finished):
            return True

        total_wanted = int(status.total_wanted)
        return total_wanted > 0 and int(status.total_wanted_done) >= total_wanted

    def _parse_magnet_link(self, magnet_link: str) -> tuple[str, str]:
        query = parse_qs(urlsplit(magnet_link.strip()).query)
        xt_values = query.get("xt", [])
        torrent_id = next(
            (value.rsplit(":", maxsplit=1)[-1].lower() for value in xt_values if value.startswith("urn:btih:")),
            None,
        )
        if torrent_id is None:
            raise ValueError(f"Invalid magnet link: {magnet_link}")

        raw_name = query.get("dn", [torrent_id])[0]
        return torrent_id, unquote_plus(raw_name)

    def _resolve_torrent_id(self, status: lt.torrent_status) -> str:
        info_hashes = status.handle.info_hashes()
        v1_hash = getattr(info_hashes, "v1", None)
        if v1_hash:
            return str(v1_hash)
        return str(info_hashes)

    def _log_tracker_alert(
        self,
        alert: lt.tracker_error_alert | lt.tracker_warning_alert,
    ) -> None:
        message = alert.message()
        normalized_message = re.sub(r"\(\d+\)\s*$", "", message).strip()
        lowered = normalized_message.lower()

        if "skipping tracker announce" in lowered and "unreachable" in lowered:
            return

        if normalized_message in self._seen_tracker_alerts:
            return
        self._seen_tracker_alerts.add(normalized_message)
        LOGGER.warning(normalized_message)

    def _start_network_services(self, session: lt.session) -> None:
        for method_name in ("start_dht", "start_lsd", "start_natpmp", "start_upnp"):
            method = getattr(session, method_name, None)
            if method is None:
                continue
            method()


__all__ = ["TorrentClient"]
