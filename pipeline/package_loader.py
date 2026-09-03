from __future__ import annotations

import tarfile
from pathlib import Path


class PackageExtractionError(RuntimeError):
    pass


def _safe_extract(
    archive: tarfile.TarFile,
    destination: Path,
) -> None:
    destination = destination.resolve()

    for member in archive.getmembers():
        member_path = (
            destination / member.name
        ).resolve()

        if not str(member_path).startswith(
            str(destination) + "/"
        ):
            raise PackageExtractionError(
                "Unsafe path detected in archive: "
                f"{member.name}"
            )

    archive.extractall(destination)


def extract_package(
    archive_path: Path,
    destination: Path,
) -> Path:

    archive_path = Path(
        archive_path
    ).resolve()

    destination = Path(
        destination
    ).resolve()

    if not archive_path.exists():
        raise FileNotFoundError(
            f"Package archive not found: "
            f"{archive_path}"
        )

    if not archive_path.is_file():
        raise PackageExtractionError(
            f"Package archive is not a file: "
            f"{archive_path}"
        )

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        with tarfile.open(
            archive_path,
            mode="r:gz",
        ) as archive:

            _safe_extract(
                archive,
                destination,
            )

    except tarfile.TarError as exc:
        raise PackageExtractionError(
            f"Invalid tar.gz archive: "
            f"{archive_path}"
        ) from exc

    return find_package_root(destination)


def find_package_root(
    extracted_directory: Path,
) -> Path:

    extracted_directory = Path(
        extracted_directory
    ).resolve()

    entries = list(
        extracted_directory.iterdir()
    )

    directories = [
        path
        for path in entries
        if path.is_dir()
    ]

    files = [
        path
        for path in entries
        if path.is_file()
    ]

    if (
        (
            extracted_directory / "pyproject.toml"
        ).exists()
        or
        (
            extracted_directory / "setup.py"
        ).exists()
        or
        (
            extracted_directory / "setup.cfg"
        ).exists()
    ):
        return extracted_directory

    package_directories = [
        path
        for path in directories
        if (
            (path / "pyproject.toml").exists()
            or
            (path / "setup.py").exists()
            or
            (path / "setup.cfg").exists()
        )
    ]

    if len(package_directories) == 1:
        return package_directories[0]

    if len(directories) == 1 and not files:
        return find_package_root(
            directories[0]
        )

    raise PackageExtractionError(
        "Could not determine package root "
        f"inside {extracted_directory}"
    )


def collect_python_files(
    package_root: Path,
) -> list[Path]:

    package_root = Path(
        package_root
    ).resolve()

    return sorted(
        path
        for path in package_root.rglob("*.py")
        if path.is_file()
    )


def load_package_source(
    package_root: Path,
) -> dict:

    python_files = collect_python_files(
        package_root
    )

    if not python_files:
        raise PackageExtractionError(
            f"No Python files found in "
            f"{package_root}"
        )

    files = {}

    for path in python_files:
        relative_path = path.relative_to(
            package_root
        )

        files[str(relative_path)] = (
            path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        )

    return files