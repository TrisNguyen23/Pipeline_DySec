from __future__ import annotations

import shutil
import tarfile
from pathlib import Path


class PackageExtractionError(RuntimeError):
    pass


# setup.py is intentionally allowed as a mutation target because
# the malicious packages in this dataset place their relevant
# installation behaviour there.
#
# Other packaging/configuration files are not mutation targets.
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

    files = [
        path
        for path in package_root.rglob("*.py")
        if (
            path.is_file()
            and path.stat().st_size > 0
        )
    ]

    return sorted(files)


def collect_transformable_python_files(
    package_root: Path,
) -> list[Path]:

    package_root = Path(
        package_root
    ).resolve()

    setup_py = package_root / "setup.py"

    # setup.py is the primary mutation target for this dataset.
    # If it exists and contains source, use it directly.
    if (
        setup_py.is_file()
        and setup_py.stat().st_size > 0
    ):
        return [setup_py]

    candidates: list[Path] = []

    for path in package_root.rglob("*.py"):

        if not path.is_file():
            continue

        if path.stat().st_size == 0:
            continue

        relative_path = path.relative_to(
            package_root
        )

        # Never mutate tests.
        if any(
            part.lower() in {
                "test",
                "tests",
            }
            for part in relative_path.parts
        ):
            continue

        # setup.py was already handled above.
        #
        # Other packaging/configuration Python files should
        # not become mutation targets.
        if path.name in NON_MUTATABLE_PACKAGING_FILES:
            continue

        # Empty __init__.py files are already excluded by
        # the size check. Non-empty __init__.py files remain
        # valid implementation candidates when no setup.py
        # target exists.
        candidates.append(path)

    # Prefer actual implementation files over __init__.py.
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
    package_root = Path(package_root).resolve()
    archive_path = Path(archive_path).resolve()

    if not package_root.exists():
        raise FileNotFoundError(
            f"Package root does not exist: {package_root}"
        )

    archive_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if archive_path.exists():
        archive_path.unlink()

    with tarfile.open(
        archive_path,
        "w:gz",
    ) as archive:
        for path in sorted(package_root.rglob("*")):
            archive.add(
                path,
                arcname=path.relative_to(
                    package_root.parent
                ),
                recursive=False,
            )

    return archive_path