import shutil
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, urlsplit

import libtorrent as lt

BTIH_LENGTHS = {32, 40}
DEFAULT_POLL_INTERVAL = 0.2
DEFAULT_LISTEN_INTERFACES = "0.0.0.0:6881,[::]:6881"
DEFAULT_CONNECTIONS_PER_TORRENT = 80


@dataclass(slots=True)
class MagnetMetadata:
    magnet: str
    info_hash: str
    name: str | None = None
    total_size: int | None = None
    files: list[dict[str, int | str]] | None = None
    error: str | None = None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and self.total_size is not None


@dataclass(slots=True)
class DownloadResult:
    magnet: str
    info_hash: str
    destination: Path
    name: str | None = None
    total_size: int = 0
    downloaded: int = 0
    progress: float = 0.0
    peers: int = 0
    completed: bool = False
    timed_out: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.completed and self.error is None


@dataclass(slots=True)
class MetadataProgress:
    fetched: int
    total: int


@dataclass(slots=True)
class DownloadProgress:
    download_rate: int
    downloaded: int
    total_size: int
    peers: int


@dataclass(slots=True)
class _Job:
    magnet: str
    info_hash: str
    destination: Path
    metadata_only: bool
    metadata: MagnetMetadata | None = None
    result: DownloadResult | None = None
    added_at: float | None = None
    metadata_at: float | None = None


class LibtorrentMagnetClient:
    """Standalone high-throughput helper for magnet metadata and downloads."""

    def __init__(
            self,
            *,
            listen_interfaces: str = DEFAULT_LISTEN_INTERFACES,
            poll_interval: float = DEFAULT_POLL_INTERVAL,
            alert_queue_size: int = 10000,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than 0")

        self.listen_interfaces = listen_interfaces
        self.poll_interval = poll_interval
        self.alert_queue_size = alert_queue_size
        self._metadata_dir = Path(tempfile.mkdtemp(prefix="lt-metadata-"))
        self._session: lt.session | None = None

    def close(self) -> None:
        if self._session is not None:
            self._session.pause()
            self._session = None
        shutil.rmtree(self._metadata_dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @staticmethod
    def validate_magnet(magnet: object) -> bool:
        if magnet is None:
            return False

        raw = str(magnet).strip()
        if not raw:
            return False

        parsed = urlsplit(raw)
        if parsed.scheme != "magnet":
            return False

        xt_values = parse_qs(parsed.query).get("xt", [])
        btih = next(
            (
                value.rsplit(":", maxsplit=1)[-1]
                for value in xt_values
                if value.startswith("urn:btih:")
            ),
            None,
        )
        return bool(btih and len(btih) in BTIH_LENGTHS)

    @staticmethod
    def info_hash_from_magnet(magnet: str) -> str:
        xt_values = parse_qs(urlsplit(magnet.strip()).query).get("xt", [])
        info_hash = next(
            (
                value.rsplit(":", maxsplit=1)[-1].lower()
                for value in xt_values
                if value.startswith("urn:btih:")
            ),
            None,
        )
        if info_hash is None:
            raise ValueError(f"Invalid magnet link: {magnet}")
        return info_hash

    def fetch_metadata(
            self,
            magnets: Iterable[str],
            *,
            timeout: float = 90.0,
            max_parallel: int = 200,
            progress_callback: Callable[[MetadataProgress], None] | None = None,
    ) -> list[MagnetMetadata]:
        jobs = self._prepare_jobs(magnets, self._metadata_dir, metadata_only=True)
        if not jobs:
            return []

        self._run_jobs(
            jobs,
            max_parallel=max_parallel,
            timeout=timeout,
            metadata_timeout=timeout,
            metadata_progress_callback=progress_callback,
            download_progress_callback=None,
        )
        return [job.metadata for job in jobs if job.metadata is not None]

    def download(
            self,
            magnets: Iterable[str],
            *,
            destination: str | Path,
            expected_sizes: Mapping[str, int] | None = None,
            timeout: float | None = None,
            metadata_timeout: float = 120.0,
            max_parallel: int = 8,
            progress_callback: Callable[[DownloadProgress], None] | None = None,
            completion_callback: Callable[[DownloadResult], None] | None = None,
    ) -> list[DownloadResult]:
        destination_path = Path(destination).expanduser().resolve()
        destination_path.mkdir(parents=True, exist_ok=True)

        jobs = self._prepare_jobs(
            magnets,
            destination_path,
            metadata_only=False,
            expected_sizes=expected_sizes,
        )
        if not jobs:
            return []

        self._run_jobs(
            jobs,
            max_parallel=max_parallel,
            timeout=timeout,
            metadata_timeout=metadata_timeout,
            metadata_progress_callback=None,
            download_progress_callback=progress_callback,
        )

        results = [job.result for job in jobs if job.result is not None]
        if completion_callback is not None:
            for result in results:
                if result.completed:
                    completion_callback(result)
        return results

    def _prepare_jobs(
            self,
            magnets: Iterable[str],
            destination: Path,
            *,
            metadata_only: bool,
            expected_sizes: Mapping[str, int] | None = None,
    ) -> list[_Job]:
        ordered_unique: list[str] = list(
            dict.fromkeys(str(magnet).strip() for magnet in magnets if str(magnet).strip()))
        jobs: list[_Job] = []
        for magnet in ordered_unique:
            info_hash = self.info_hash_from_magnet(magnet)
            expected_size = 0
            if expected_sizes is not None:
                expected_size = max(int(expected_sizes.get(magnet, 0)), 0)
            jobs.append(
                _Job(
                    magnet=magnet,
                    info_hash=info_hash,
                    destination=destination,
                    metadata_only=metadata_only,
                    metadata=MagnetMetadata(
                        magnet=magnet,
                        info_hash=info_hash,
                        total_size=expected_size or None,
                    ),
                    result=DownloadResult(
                        magnet=magnet,
                        info_hash=info_hash,
                        destination=destination,
                        total_size=expected_size,
                    ),
                )
            )
        return jobs

    def _ensure_session(self, *, max_parallel: int) -> lt.session:
        settings = self._build_session_settings(max_parallel=max_parallel)
        if self._session is None:
            self._session = lt.session(settings)
            self._start_network_services(self._session)
        else:
            self._session.apply_settings(settings)

        self._session.set_download_rate_limit(0)
        self._session.set_local_download_rate_limit(0)
        return self._session

    def _build_session_settings(self, *, max_parallel: int) -> dict[str, int | str | bool]:
        connections_limit = max(1000, max_parallel * DEFAULT_CONNECTIONS_PER_TORRENT)
        return {
            "listen_interfaces": self.listen_interfaces,
            "enable_dht": True,
            "enable_lsd": True,
            "enable_upnp": True,
            "enable_natpmp": True,
            "alert_mask": int(
                lt.alert.category_t.error_notification
                | lt.alert.category_t.status_notification
                | lt.alert.category_t.storage_notification
                | lt.alert.category_t.performance_warning
                | lt.alert.category_t.tracker_notification
            ),
            "alert_queue_size": self.alert_queue_size,
            "connection_speed": 200,
            "connections_limit": connections_limit,
            "active_limit": max_parallel,
            "active_downloads": max_parallel,
            "active_seeds": 0,
            "active_checking": max_parallel,
            "max_queued_disk_bytes": 16 * 1024 * 1024,
            "unchoke_slots_limit": 0,
            "num_optimistic_unchoke_slots": 0,
            "seeding_outgoing_connections": False,
        }

    def _run_jobs(
            self,
            jobs: list[_Job],
            *,
            max_parallel: int,
            timeout: float | None,
            metadata_timeout: float,
            metadata_progress_callback: Callable[[MetadataProgress], None] | None,
            download_progress_callback: Callable[[DownloadProgress], None] | None,
    ) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be at least 1")

        session = self._ensure_session(max_parallel=max_parallel)
        pending = iter(jobs)
        active: dict[lt.torrent_handle, _Job] = {}
        deadline = None if timeout is None else time.monotonic() + timeout
        metadata_reported = -1

        def add_next() -> bool:
            try:
                job = next(pending)
            except StopIteration:
                return False

            params = lt.parse_magnet_uri(job.magnet)
            params.save_path = str(job.destination)
            params.flags |= lt.torrent_flags.duplicate_is_error
            params.max_uploads = 0
            params.upload_limit = 0
            if job.metadata_only:
                params.flags |= lt.torrent_flags.upload_mode
            handle = session.add_torrent(params)
            job.added_at = time.monotonic()
            active[handle] = job
            return True

        for _ in range(min(max_parallel, len(jobs))):
            add_next()

        while active:
            session.post_torrent_updates()
            for alert in session.pop_alerts():
                self._handle_alert(alert, active)

            finished: list[lt.torrent_handle] = []
            now = time.monotonic()

            for handle, job in list(active.items()):
                status = handle.status()
                self._sync_job_from_status(job, status)

                if status.errc.value():
                    self._mark_error(job, status.errc.message())
                    finished.append(handle)
                    continue

                if job.metadata is not None and job.metadata.total_size is None and status.has_metadata:
                    self._fill_metadata(job, handle)

                if job.metadata_only and job.metadata is not None and job.metadata.ok:
                    finished.append(handle)
                    continue

                if not job.metadata_only and self._is_finished(status):
                    self._mark_completed(job)
                    finished.append(handle)
                    continue

                if deadline is not None and now >= deadline:
                    self._mark_timeout(job, "overall timeout")
                    finished.append(handle)
                    continue

                if (
                    job.added_at is not None
                    and job.metadata_at is None
                    and (now - job.added_at) >= metadata_timeout
                ):
                    self._mark_timeout(job, "metadata timeout")
                    finished.append(handle)

            if metadata_progress_callback is not None:
                fetched = sum(1 for job in jobs if
                              job.metadata is not None and (job.metadata.ok or job.metadata.error is not None))
                if fetched != metadata_reported:
                    metadata_reported = fetched
                    metadata_progress_callback(MetadataProgress(fetched=fetched, total=len(jobs)))

            if download_progress_callback is not None and any(not job.metadata_only for job in jobs):
                download_progress_callback(self._build_download_progress(jobs, active))

            for handle in finished:
                self._remove_handle(session, handle)
                active.pop(handle, None)
                add_next()

            if active:
                time.sleep(self.poll_interval)

    def _handle_alert(self, alert: lt.alert, active: dict[lt.torrent_handle, _Job]) -> None:
        handle = getattr(alert, "handle", None)
        if handle is None:
            return
        job = active.get(handle)
        if job is None:
            return

        if isinstance(alert, lt.metadata_received_alert):
            self._fill_metadata(job, handle)
            return

        if isinstance(alert, lt.torrent_error_alert):
            self._mark_error(job, alert.error.message())
            return

        if isinstance(alert, lt.add_torrent_alert) and alert.error.value():
            self._mark_error(job, alert.error.message())

    def _sync_job_from_status(self, job: _Job, status: lt.torrent_status) -> None:
        if job.result is None:
            return

        job.result.name = str(status.name or job.result.name or "")
        job.result.total_size = max(int(status.total_wanted), job.result.total_size)
        job.result.downloaded = max(int(status.total_wanted_done), job.result.downloaded)
        job.result.peers = max(int(status.num_peers), 0)
        if job.result.total_size > 0:
            job.result.progress = min(1.0, job.result.downloaded / job.result.total_size)
        elif status.progress >= 0:
            job.result.progress = float(status.progress)

    def _fill_metadata(self, job: _Job, handle: lt.torrent_handle) -> None:
        if job.metadata is None:
            return

        info = handle.torrent_file()
        if info is None:
            return

        files = info.files()
        job.metadata.name = info.name()
        job.metadata.total_size = info.total_size()
        job.metadata.files = [
            {
                "path": files.file_path(index),
                "size": files.file_size(index),
            }
            for index in range(files.num_files())
        ]
        job.metadata_at = time.monotonic()

        if job.result is not None:
            job.result.name = job.metadata.name
            job.result.total_size = max(job.result.total_size, job.metadata.total_size or 0)

    def _build_download_progress(
            self,
            jobs: list[_Job],
            active: dict[lt.torrent_handle, _Job],
    ) -> DownloadProgress:
        total_rate = 0
        total_peers = 0
        total_downloaded = 0

        for handle, job in active.items():
            if job.metadata_only:
                continue

            status = handle.status()
            total_rate += max(int(status.download_rate), 0)
            total_peers += max(int(status.num_peers), 0)

        for job in jobs:
            if job.metadata_only or job.result is None:
                continue
            total_downloaded += max(int(job.result.downloaded), 0)

        return DownloadProgress(
            download_rate=total_rate,
            downloaded=total_downloaded,
            total_size=sum(
                max(int(job.result.total_size), 0)
                for job in jobs
                if not job.metadata_only and job.result is not None
            ),
            peers=total_peers,
        )

    def _mark_completed(self, job: _Job) -> None:
        if job.result is None:
            return

        if job.metadata is not None and not job.metadata.ok:
            job.metadata.error = None
            job.metadata.timed_out = False
            job.metadata_at = job.metadata_at or time.monotonic()
        job.result.completed = True
        job.result.progress = 1.0
        job.result.downloaded = max(job.result.downloaded, job.result.total_size)

    def _mark_timeout(self, job: _Job, message: str) -> None:
        if job.metadata is not None and job.metadata.total_size is None and job.metadata.error is None:
            job.metadata.timed_out = True
            job.metadata.error = message
        if job.result is not None and not job.result.completed and job.result.error is None:
            job.result.timed_out = True
            job.result.error = message

    def _mark_error(self, job: _Job, message: str) -> None:
        if job.metadata is not None and job.metadata.total_size is None and job.metadata.error is None:
            job.metadata.error = message
        if job.result is not None and job.result.error is None:
            job.result.error = message

    def _remove_handle(self, session: lt.session, handle: lt.torrent_handle) -> None:
        if handle.is_valid():
            session.remove_torrent(handle)

    def _is_finished(self, status: lt.torrent_status) -> bool:
        if bool(status.is_seeding) or bool(status.is_finished):
            return True

        total_wanted = int(status.total_wanted)
        return total_wanted > 0 and int(status.total_wanted_done) >= total_wanted

    def _start_network_services(self, session: lt.session) -> None:
        for method_name in ("start_dht", "start_lsd", "start_natpmp", "start_upnp"):
            method = getattr(session, method_name, None)
            if method is not None:
                method()


__all__ = [
    "DownloadProgress",
    "DownloadResult",
    "LibtorrentMagnetClient",
    "MagnetMetadata",
    "MetadataProgress",
]
