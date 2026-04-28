from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.text import Text

from jonepace.libtorrent_wrapper import DownloadProgress, MetadataProgress

TOOL_NAME = "JONEPACE"
TITLE_ART = r"""
     __  ____  _   _____________  ___   ________
    / / / __ \/ | / / ____/ __ \/   | / ____/ /
   / / / / / /  |/ / __/ / /_/ / /| |/ /   / / 
  / /_/ /_/ / /|  / /___/ ____/ ___ / /___/ /___
  \____/\____/_/ |_/_____/_/   /_/  |_\____/_____/
""".strip("\n")


def _tool_version() -> str:
    try:
        return version("jonepace")
    except PackageNotFoundError:
        return "dev"


def welcome() -> None:
    console = Console()
    title = Text(TITLE_ART, style="bold cyan")
    subtitle = Text(f"v{_tool_version()}", style="bold white")

    body = Group(
        Align.center(title),
        Text(""),
        Align.center(subtitle),
    )

    console.print(
        Panel(
            body,
            title=TOOL_NAME,
            title_align="center",
            border_style="bright_blue",
            padding=(1, 3),
        )
    )

class PeersCountColumn(ProgressColumn):
    def render(self, task: "Task") -> Text:
        peers = int(task.fields.get("peers", 0))
        clamped = max(0, min(peers, 20))
        red = int(255 * (20 - clamped) / 20)
        green = int(255 * clamped / 20)
        return Text(f"peers: {peers}", style=f"rgb({red},{green},0)")


@contextmanager
def metadata_progress_sink(description: str = "Fetching torrent metadata") -> Iterator[
    Callable[[MetadataProgress], None]]:
    with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(elapsed_when_finished=True),
    ) as progress:
        task_id = progress.add_task(description, total=0)

        def update(state: MetadataProgress) -> None:
            progress.update(task_id, total=state.total, completed=state.fetched)

        yield update


@contextmanager
def download_progress_sink(description: str = "Downloading torrents") -> Iterator[
    Callable[[DownloadProgress], None]]:
    last_downloaded = 0

    with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            DownloadColumn(binary_units=True),
            TransferSpeedColumn(),
            PeersCountColumn(),
            TimeRemainingColumn(elapsed_when_finished=True),
    ) as progress:
        task_id = progress.add_task(
            description,
            total=0,
            completed=0,
            peers=0,
        )

        def update(state: DownloadProgress) -> None:
            nonlocal last_downloaded
            advance = max(0, state.downloaded - last_downloaded)
            last_downloaded = state.downloaded
            progress.update(
                task_id,
                total=state.total_size,
                advance=advance,
                peers=state.peers,
            )

        yield update
