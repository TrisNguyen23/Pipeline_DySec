from __future__ import annotations

import json
import os
import tarfile
import tempfile
import threading
from pathlib import Path
from typing import Any
import requests

DYSEC_API_URL = os.getenv("DYSEC_API_URL", "https://api.dysec.io/v1/scan")
DYSEC_API_KEY = os.getenv("DYSEC_API_KEY", "")

CACHE_FILE = Path(__file__).resolve().parent.parent / ".linux_compat_cache.json"
_compat_cache: dict[str, bool] = {}
_cache_loaded = False
_cache_dirty = False
_cache_lock = threading.Lock()

# Windows-exclusive keywords (Strict Blacklist)
WINDOWS_INDICATORS = (
    b"ctypes.windll",
    b"winreg",
    b"powershell",
    b"cmd.exe",
    b"HKEY_LOCAL_MACHINE",
    b"HKEY_CURRENT_USER",
    b"WinMain",
    b"System32",
    b"AppData\\Local",
)

# Linux/POSIX runtime & network indicators triggered during installation (DySec eBPF relevant)
LINUX_ACTIVE_INDICATORS = (
    b"/bin/sh",
    b"/bin/bash",
    b"/etc/",
    b"/tmp/",
    b"subprocess",
    b"os.system",
    b"os.popen",
    b"socket.",
    b"pty.spawn",
    b"requests.",
    b"urllib.",
    b"base64.b64decode",
    b"exec(",
)


def _load_cache() -> None:
    global _compat_cache, _cache_loaded
    if _cache_loaded:
        return
    with _cache_lock:
        if _cache_loaded:
            return
        if CACHE_FILE.is_file():
            try:
                data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    _compat_cache = {str(k): bool(v) for k, v in data.items()}
            except Exception:
                _compat_cache = {}
        _cache_loaded = True


def flush_compat_cache() -> None:
    """Safely persist the in-memory compatibility cache to disk using atomic replacement."""
    global _cache_dirty
    with _cache_lock:
        if not _cache_dirty:
            return
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            temp_file = CACHE_FILE.with_suffix(f".tmp_{os.getpid()}_{threading.get_ident()}")
            temp_file.write_text(json.dumps(_compat_cache, indent=2), encoding="utf-8")
            temp_file.replace(CACHE_FILE)
            _cache_dirty = False
        except Exception:
            pass


def is_linux_compatible(archive_path: Path) -> bool:
    """Verify if a package is Linux-compatible and active for DySec eBPF dynamic monitoring."""
    global _cache_dirty
    _load_cache()

    try:
        resolved_key = str(archive_path.resolve())
    except Exception:
        resolved_key = str(archive_path)

    with _cache_lock:
        if resolved_key in _compat_cache:
            return _compat_cache[resolved_key]

    is_compatible = False
    has_windows_signals = False
    has_linux_signals = False

    try:
        with tarfile.open(archive_path, "r:*") as tar:
            members = tar.getmembers()

            # Prioritize entry points (setup.py, __init__.py) where install-time execution resides
            python_members = [
                m for m in members
                if m.isfile() and m.name.endswith(".py") and m.size <= 256 * 1024
            ]
            python_members.sort(
                key=lambda m: (0 if m.name.endswith("setup.py") else (1 if m.name.endswith("__init__.py") else 2))
            )

            # Check up to 8 prioritized Python files
            for member in python_members[:8]:
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                content = extracted.read(65536)

                if any(w in content for w in WINDOWS_INDICATORS):
                    has_windows_signals = True
                    break

                if any(ind in content for ind in LINUX_ACTIVE_INDICATORS):
                    has_linux_signals = True

            # Must not contain Windows exclusive calls, and should carry functional/dynamic hooks
            if not has_windows_signals and has_linux_signals:
                is_compatible = True
            elif not has_windows_signals and len(python_members) > 0:
                # Fallback: pure standard package without Windows exclusivity
                is_compatible = True

    except Exception:
        # Malformed or unreadable archives should not be classified as compatible
        is_compatible = False

    with _cache_lock:
        _compat_cache[resolved_key] = is_compatible
        _cache_dirty = True

    return is_compatible


def evaluate_with_dysec(archive_path: Path, timeout: int = 120) -> dict[str, Any]:
    """Submit a package archive to DySec.io and return the standardized verdict."""
    if not DYSEC_API_URL or os.getenv("DYSEC_MODE", "auto") == "manual":
        return {"status": "AWAITING_DYSEC", "verdict": None}

    headers = {"Authorization": f"Bearer {DYSEC_API_KEY}"} if DYSEC_API_KEY else {}
    try:
        with archive_path.open("rb") as f:
            files = {"file": (archive_path.name, f, "application/gzip")}
            resp = requests.post(DYSEC_API_URL, headers=headers, files=files, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()

        raw_verdict = str(data.get("verdict") or data.get("classification") or "DETECTED").upper()
        norm_verdict = "NOT_DETECTED" if raw_verdict in {"BENIGN", "NOT_DETECTED"} else "DETECTED"

        return {
            "status": "SUCCESS" if norm_verdict == "NOT_DETECTED" else "DETECTED",
            "verdict": norm_verdict,
            "score": data.get("score"),
            "features": data.get("features", {}),
            "raw": data,
        }
    except Exception as exc:
        return {"status": "AWAITING_DYSEC", "verdict": None, "error": str(exc)}