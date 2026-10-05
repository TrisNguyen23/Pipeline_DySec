from __future__ import annotations

import shutil
import tarfile
from pathlib import Path


class PackageExtractionError(RuntimeError):
    pass


NON_MUTATABLE_PACKAGING_FILES = {
    "setup.cfg",
    "pyproject.toml",
    "MANIFEST.in",
}


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

            try:
                member_path.relative_to(
                    destination_root
                )
            except ValueError:
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
        if (
            path.is_file()
            and path.stat().st_size > 0
        )
    )


def collect_transformable_python_files(
    package_root: Path,
) -> list[Path]:

    package_root = Path(
        package_root
    ).resolve()

    candidates: list[Path] = []

    for path in package_root.rglob("*.py"):

        if not path.is_file():
            continue

        if path.stat().st_size == 0:
            continue

        relative_path = path.relative_to(
            package_root
        )

        # Do not mutate test code.
        if any(
            part.lower() in {
                "test",
                "tests",
            }
            for part in relative_path.parts
        ):
            continue

        # setup.py holds special meaning in packaging, so we avoid mutating it.
        # Python code can be analyzed/mutated.
        candidates.append(path)

    # Prefer regular Python modules.
    # If only __init__.py is present, keep it
    # for the AST/function analysis step to decide
    # whether it has mutation targets.
    non_init_files = [
        path
        for path in candidates
        if path.name != "__init__.py"
    ]

    if non_init_files:
        return sorted(non_init_files)

    return sorted(candidates)


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


def create_package_archive(
    package_root: Path,
    archive_path: Path,
) -> Path:

    package_root = Path(
        package_root
    ).resolve()

    archive_path = Path(
        archive_path
    ).resolve()

    if not package_root.exists():
        raise FileNotFoundError(
            f"Package root does not exist: "
            f"{package_root}"
        )

    archive_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if archive_path.exists():
        archive_path.unlink()

    base_dir = package_root.parent

    with tarfile.open(
        archive_path,
        "w:gz",
    ) as archive:

        for path in sorted(
            package_root.rglob("*")
        ):

            relative_path = path.relative_to(
                base_dir
            )

            archive.add(
                path,
                arcname=relative_path,
                recursive=False,
            )

    return archive_path