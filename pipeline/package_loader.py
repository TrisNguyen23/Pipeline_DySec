from __future__ import annotations

import shutil
import tarfile
from pathlib import Path


class PackageExtractionError(RuntimeError):
    pass


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

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    with tarfile.open(
        archive_path,
        "r:gz",
    ) as archive:

        destination_root = destination.resolve()

        for member in archive.getmembers():

            member_path = (
                destination_root
                / member.name
            ).resolve()

            if not str(member_path).startswith(
                str(destination_root) + "/"
            ):
                raise PackageExtractionError(
                    f"Unsafe archive path: "
                    f"{member.name}"
                )

            if member.issym() or member.islnk():
                raise PackageExtractionError(
                    f"Links are not allowed in "
                    f"package archive: {member.name}"
                )

        archive.extractall(
            destination_root
        )

    return find_package_root(
        destination_root
    )


def find_package_root(
    extracted_directory: Path,
) -> Path:

    extracted_directory = Path(
        extracted_directory
    ).resolve()

    if (
        (extracted_directory / "pyproject.toml").exists()
        or
        (extracted_directory / "setup.py").exists()
        or
        (extracted_directory / "setup.cfg").exists()
    ):
        return extracted_directory

    directories = sorted(
        path
        for path in extracted_directory.iterdir()
        if path.is_dir()
    )

    package_roots = [
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

    if len(package_roots) == 1:
        return package_roots[0]

    if len(directories) == 1:
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


def copy_package(
    source: Path,
    destination: Path,
) -> Path:

    source = Path(source).resolve()
    destination = Path(destination).resolve()

    if not source.exists():
        raise FileNotFoundError(
            f"Package does not exist: {source}"
        )

    if destination.exists():
        shutil.rmtree(destination)

    shutil.copytree(
        source,
        destination,
    )

    return destination