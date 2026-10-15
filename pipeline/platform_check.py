from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

# Modules that only exist / only matter on Windows. Importing one of
# these, unconditionally, is strong evidence the package is Windows-only.
WINDOWS_ONLY_IMPORTS = {
    "winreg",
    "winsound",
    "win32api",
    "win32con",
    "win32com",
    "win32file",
    "win32gui",
    "win32process",
    "win32security",
    "win32event",
    "win32pipe",
    "pywintypes",
    "pythoncom",
    "msvcrt",
    "_winapi",
    "ctypes.wintypes",
}

# setup.py / setup.cfg / pyproject.toml classifier strings that declare
# a Windows-only (and not cross-platform) audience.
WINDOWS_CLASSIFIER_RE = re.compile(
    r"Operating System :: Microsoft :: Windows",
    re.IGNORECASE,
)

# Classifiers that indicate the package explicitly also targets
# non-Windows platforms (POSIX, Linux, macOS, OS Independent).
CROSS_PLATFORM_CLASSIFIER_RE = re.compile(
    r"Operating System :: (POSIX|Unix|MacOS|OS Independent)",
    re.IGNORECASE,
)


def _imports_from_source(source_code: str) -> set[str]:
    """
    Best-effort extraction of top-level imported module names from a
    single Python source file. Invalid syntax yields an empty set
    rather than raising, since platform detection should never block
    a package for an unrelated parse failure (the existing syntax gate
    already handles that case separately).
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return set()

    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)

    return names


def _classifiers_text(package_root: Path) -> str:
    """
    Concatenate the text of setup.py, setup.cfg, and pyproject.toml if
    present, for a simple substring/regex scan. A full TOML/INI parse
    is unnecessary here since we only look for classifier strings.
    """
    chunks: list[str] = []

    for name in ("setup.py", "setup.cfg", "pyproject.toml"):
        candidate = package_root / name
        if candidate.is_file():
            try:
                chunks.append(
                    candidate.read_text(
                        encoding="utf-8",
                        errors="ignore",
                    )
                )
            except OSError:
                continue

    return "\n".join(chunks)


def detect_platform_scope(
    package_root: Path,
    python_sources: dict[str, str],
) -> dict[str, Any]:
    """
    Decide whether a package is Windows-only.

    Signals, in order of confidence:
      1. A Windows classifier is declared AND no cross-platform
         classifier is declared alongside it -> windows_only.
      2. Any source file unconditionally imports a Windows-only
         module (not inside a try/except or an os.name == "nt"
         guard is not distinguished here; any such import is treated
         as a signal, since even a guarded import means the package
         carries Windows-specific code paths the mutation pipeline
         was not designed to validate) -> windows_only.
      3. Otherwise -> not windows_only.

    This is a heuristic, not a certainty: it can both miss genuinely
    Windows-only packages (e.g. ones gated entirely behind a runtime
    sys.platform check with no static import) and flag a package that
    merely supports Windows as one of several platforms. Classifier
    evidence is treated as authoritative when present because it is
    the package author's own declaration.
    """
    package_root = Path(package_root)

    classifiers_text = _classifiers_text(package_root)
    has_windows_classifier = bool(
        WINDOWS_CLASSIFIER_RE.search(classifiers_text)
    )
    has_cross_platform_classifier = bool(
        CROSS_PLATFORM_CLASSIFIER_RE.search(classifiers_text)
    )

    if has_windows_classifier and not has_cross_platform_classifier:
        return {
            "windows_only": True,
            "reason": (
                "setup metadata declares a Windows classifier with no "
                "accompanying cross-platform classifier."
            ),
            "evidence": "classifier",
        }

    windows_imports_found: dict[str, set[str]] = {}

    for source_path, source_code in python_sources.items():
        imports = _imports_from_source(source_code)
        hit = imports & WINDOWS_ONLY_IMPORTS
        if hit:
            windows_imports_found[source_path] = hit

    if windows_imports_found:
        return {
            "windows_only": True,
            "reason": (
                "source file(s) import Windows-only modules: "
                f"{windows_imports_found}"
            ),
            "evidence": "import",
        }

    return {
        "windows_only": False,
        "reason": None,
        "evidence": None,
    }
