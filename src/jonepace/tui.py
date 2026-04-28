from collections.abc import Callable, Iterator
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version

from rich.console import Console
from rich.prompt import Confirm
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.text import Text

from jonepace.libtorrent_wrapper import DownloadProgress, MetadataProgress


def _tool_version() -> str:
    try:
        return version("jonepace")
    except PackageNotFoundError:
        return "dev"


def welcome() -> None:
    console = Console()
    name = Text("JONEPACE", style="bold white")
    subtitle = Text(f"Version {_tool_version()}", style="dim")

    console.print()
    console.print(name)
    console.print(subtitle)
    console.print()


def confirm_download(total_size_bytes: int, count: int) -> bool:
    console = Console()
    total_size_gb = total_size_bytes / 1000 ** 3
    return Confirm.ask(
        f"Download {count} torrents for {total_size_gb:.2f} GB?",
        console=console,
        default=True,
    )


class PeersCountColumn(ProgressColumn):
    def render(self, task: "Task") -> Text:
        peers = int(task.fields.get("peers", 0))
        clamped = max(0, min(peers, 20))
        red = int(255 * (20 - clamped) / 20)
        green = int(255 * clamped / 20)
        return Text(f"peers: {peers}", style=f"rgb({red},{green},0)")


@contextmanager
def metadata_progress_sink(description: str) -> Iterator[
    Callable[[MetadataProgress], None]]:
    with Progress(
            SpinnerColumn(),
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
def download_progress_sink(description: str) -> Iterator[
    Callable[[DownloadProgress], None]]:
    last_downloaded = 0

    with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            DownloadColumn(binary_units=False),
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
