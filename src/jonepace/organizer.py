from pathlib import Path
import re
import shutil

from pedros import get_logger

LOGGER = get_logger()
FILE_HASH_PATTERN = re.compile(r"\[([0-9A-Fa-f]{8})](?=\.[^.]+$)")


def extract_file_hash(path: Path) -> str | None:
    match = FILE_HASH_PATTERN.search(path.name)
    if match is None:
        return None

    return match.group(1).upper()


def find_files_by_hash(root: Path, suffix: str) -> dict[str, list[Path]]:
    files_by_hash: dict[str, list[Path]] = {}

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() != suffix:
            continue

        file_hash = extract_file_hash(path)
        if file_hash is None:
            continue

        files_by_hash.setdefault(file_hash, []).append(path)

    return files_by_hash


def organize_files(root: Path) -> None:
    nfo_files_by_hash = find_files_by_hash(root, ".nfo")
    mkv_files_by_hash = find_files_by_hash(root, ".mkv")

    if not nfo_files_by_hash:
        LOGGER.info(f"No .nfo files found under {root}")
        for file_hash, mkv_paths in mkv_files_by_hash.items():
            for mkv_path in mkv_paths:
                LOGGER.info(f"No matching .nfo file found for hash {file_hash}: {mkv_path.relative_to(root)}")
        return

    moved_count = 0
    for file_hash, nfo_paths in nfo_files_by_hash.items():
        if len(nfo_paths) > 1:
            LOGGER.warning(
                f"Multiple .nfo files found for hash {file_hash}; skipping move: "
                f"{', '.join(str(path.relative_to(root)) for path in nfo_paths)}"
            )
            continue

        mkv_paths = mkv_files_by_hash.get(file_hash, [])
        if not mkv_paths:
            LOGGER.info(f"No matching .mkv file found for hash {file_hash}")
            continue

        if len(mkv_paths) > 1:
            LOGGER.warning(
                f"Multiple .mkv files found for hash {file_hash}; skipping move: "
                f"{', '.join(str(path.relative_to(root)) for path in mkv_paths)}"
            )
            continue

        mkv_path = mkv_paths[0]
        nfo_path = nfo_paths[0]
        destination = nfo_path.parent / mkv_path.name
        if mkv_path == destination:
            # LOGGER.info(f".mkv already next to .nfo for hash {file_hash}: {mkv_path.relative_to(root)}")
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(mkv_path), str(destination))
        # LOGGER.info(
        #     f"Moved .mkv for hash {file_hash}: "
        #     f"{mkv_path.relative_to(root)} -> {destination.relative_to(root)}"
        # )
        moved_count += 1

    for file_hash, mkv_paths in mkv_files_by_hash.items():
        if file_hash in nfo_files_by_hash:
            continue

        for mkv_path in mkv_paths:
            LOGGER.info(f"No matching .nfo file found for hash {file_hash}: {mkv_path.relative_to(root)}")
