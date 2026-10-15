
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    jsonify,
    make_response,
    request,
    send_file,
    send_from_directory,
)
from flask_cors import CORS


# ============================================================
# PROJECT CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import OUTPUT_DIR
from pipeline.loop import SUPPORTED_METHODS, run_package
from pipeline.dysec_client import is_linux_compatible


app = Flask(
    __name__,
    static_folder=str(PROJECT_ROOT / "dashboard"),
    static_url_path="",
)

cors_origins = [
    item.strip()
    for item in os.getenv("DASHBOARD_CORS_ORIGINS", "").split(",")
    if item.strip()
]

if cors_origins:
    CORS(app, origins=cors_origins)

MALREGISTRY_ROOT = Path(
    os.getenv(
        "MALREGISTRY_ROOT",
        "/home/sandbox/Desktop/DySec/pypi_malregistry",
    )
).resolve()

OUTPUT_ROOT = Path(OUTPUT_DIR).resolve()

TERMINAL_STATUSES = {
    "SUCCESS",
    "FAILED",
    "ERROR",
    "MAX_ROUNDS_REACHED",
    "STOPPED_EARLY",
    "INVALID_DYSEC_FEEDBACK",
    "AWAITING_DYSEC",
}

# Only these artifact types may be requested through the API.
ARTIFACT_FILES = {
    "prompt": "prompt.txt",
    "raw_output": "llm_output.py",
    "normalized_output": "normalized_output.py",
    "original_target": "target_original.py",
    "reconstructed_source": "generated_source.py",
    "generation_result": "generation_result.json",
    "target_scope": "target_scope.json",
    "mutation_plan": "mutation_plan.json",
    "mutation_plan_target_validation":
        "mutation_plan_target_validation.json",
}

job_lock = threading.Lock()
state_lock = threading.Lock()

current_job: dict[str, Any] | None = None

ARCHIVE_CACHE_TTL = 3600.0
_archive_cache: list[dict[str, str]] | None = None
_archive_cache_time = 0.0
_archive_cache_lock = threading.Lock()


# ============================================================
# COMMON HELPERS
# ============================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_safe(value: Any) -> Any:
    """Convert common filesystem and Python values into JSON-safe values."""
    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    return str(value)


def safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)) and value >= 0:
        return int(value)

    return None


def safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)) and value >= 0:
        return float(value)

    return None


def is_within(path: Path, root: Path) -> bool:
    """Return whether a resolved path is contained within root."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


# ============================================================
# JOB PROGRESS AND TOKEN USAGE
# ============================================================

def update_job_progress(job_id: str, event: dict[str, Any]) -> None:
    """Publish progress, live code streams, and token metrics by round."""
    global current_job
    if not isinstance(event, dict):
        return

    with state_lock:
        if current_job is None or current_job.get("id") != job_id:
            return

        current_job["progress"] = json_safe(event)
        current_job["phase"] = event.get("phase", "RUNNING")
        current_job["message"] = event.get("message", "Pipeline is running.")
        current_job["updated_at"] = utc_now()

        if event.get("round") is not None:
            current_job["current_round"] = event["round"]

        if event.get("phase") in {"SOURCE_SELECTION", "ROUND_START"}:
            current_job["streaming_code"] = ""
            current_job["live_target_code"] = ""
            current_job["gate_results"] = {}  

        if event.get("history"):
            current_job.setdefault("result", {})["history"] = json_safe(event["history"])

        # Update original target snippet immediately when extracted
        if event.get("target_code"):
            current_job["live_target_code"] = event["target_code"]

        # Append streaming LLM code chunks or full generated target
        if event.get("streaming_code_chunk"):
            current_job["streaming_code"] = (
                current_job.get("streaming_code", "") + event["streaming_code_chunk"]
            )
        elif event.get("generated_code"):
            current_job["streaming_code"] = event["generated_code"]

        gate = event.get("gate")
        if gate is not None:
            current_job["current_gate"] = gate
            if event.get("gate_status") is not None:
                current_job.setdefault("gate_results", {})[str(gate)] = event["gate_status"]


# ============================================================
# PACKAGE REGISTRY
# ============================================================

def find_archive(
    package: str,
    version: str,
) -> Path | None:
    if not package or not version:
        return None

    if package in {".", ".."} or version in {".", ".."}:
        return None

    if any(char in package for char in ("/", "\\")):
        return None

    if any(char in version for char in ("/", "\\")):
        return None

    root = MALREGISTRY_ROOT.resolve()
    version_dir = (root / package / version).resolve()

    if not is_within(version_dir, root):
        return None

    if not version_dir.is_dir():
        return None

    archives = sorted(
        path.resolve()
        for pattern in ("*.tar.gz", "*.tgz")
        for path in version_dir.glob(pattern)
        if path.is_file() and is_within(path, root)
    )

    return archives[0] if archives else None


def list_archives() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    if not MALREGISTRY_ROOT.is_dir():
        return items

    for package_dir in sorted(MALREGISTRY_ROOT.iterdir()):
        if not package_dir.is_dir() or package_dir.name.startswith("."):
            continue

        for version_dir in sorted(package_dir.iterdir()):
            if not version_dir.is_dir() or version_dir.name.startswith("."):
                continue

            archive = find_archive(package_dir.name, version_dir.name)
            if archive is None:
                continue

            items.append(
                {
                    "package": package_dir.name,
                    "version": version_dir.name,
                    "archive": str(archive),
                    "filename": archive.name,
                }
            )

    return items


def get_cached_archives(
    force_refresh: bool = False,
) -> list[dict[str, str]]:
    global _archive_cache, _archive_cache_time

    with _archive_cache_lock:
        now = time.monotonic()

        cache_valid = (
            _archive_cache is not None
            and now - _archive_cache_time < ARCHIVE_CACHE_TTL
        )

        if cache_valid and not force_refresh:
            return _archive_cache or []

        _archive_cache = list_archives()
        _archive_cache_time = now

        return _archive_cache


# ============================================================
# SUMMARY AND ROUND ARTIFACT DISCOVERY
# ============================================================

def find_job_summary(
    job: dict[str, Any],
) -> Path | None:
    """
    Find a summary belonging to the current job.

    Preferred: pipeline result contains summary_path or summary_file.
    Compatibility fallback: newest summary matching package and method.

    The fallback is not guaranteed to identify the exact job if the pipeline
    does not persist a unique job ID or summary path.
    """
    result = job.get("result") or {}

    explicit_path = (
        result.get("summary_path")
        or result.get("summary_file")
        or job.get("summary_path")
    )

    if explicit_path:
        candidate = Path(str(explicit_path)).resolve()

        if (
            is_within(candidate, OUTPUT_ROOT)
            and candidate.is_file()
        ):
            return candidate

        return None

    package_name = result.get("package") or job.get("package")
    method = job.get("method")

    if (
        not package_name
        or method not in SUPPORTED_METHODS
        or not OUTPUT_ROOT.is_dir()
    ):
        return None

    matches: list[Path] = []

    for candidate in OUTPUT_ROOT.rglob("summary.json"):
        try:
            resolved = candidate.resolve()

            if not is_within(resolved, OUTPUT_ROOT):
                continue

            if not resolved.is_file():
                continue

            data = json.loads(
                resolved.read_text(encoding="utf-8")
            )

        except (OSError, ValueError, json.JSONDecodeError):
            continue

        experiment = data.get("experiment") or {}

        if (
            data.get("package") == package_name
            and experiment.get("method") == method
        ):
            matches.append(resolved)

    if not matches:
        return None

    return max(
        matches,
        key=lambda path: path.stat().st_mtime,
    )


def _round_tokens(round_number: int) -> set[str]:
    return {
        f"round_{round_number:02d}",
        f"round_{round_number}",
        f"round-{round_number:02d}",
        f"round-{round_number}",
    }


def find_round_directory(
    job: dict[str, Any],
    round_number: int,
) -> Path | None:
    """Find the round directory below the current summary directory."""
    if round_number < 1:
        return None

    summary_path = find_job_summary(job)

    if summary_path is None:
        return None

    summary_root = summary_path.parent.resolve()

    if not is_within(summary_root, OUTPUT_ROOT):
        return None

    tokens = _round_tokens(round_number)
    candidates: list[Path] = []

    for path in summary_root.rglob("*"):
        if not path.is_dir():
            continue

        try:
            resolved = path.resolve()

            if not is_within(resolved, OUTPUT_ROOT):
                continue

        except OSError:
            continue

        name = path.name.casefold()

        if name in tokens:
            candidates.append(resolved)

    # Support names such as package_round_01 or experiment-round-01.
    if not candidates:
        for path in summary_root.rglob("*"):
            if not path.is_dir():
                continue

            name = path.name.casefold()

            if not any(token in name for token in tokens):
                continue

            resolved = path.resolve()

            if is_within(resolved, OUTPUT_ROOT):
                candidates.append(resolved)

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda path: path.stat().st_mtime,
    )


def read_artifact(
    directory: Path,
    filename: str,
) -> dict[str, Any] | None:
    """Read one allowlisted text artifact without executing it."""
    candidate = (directory / filename).resolve()

    if not is_within(candidate, OUTPUT_ROOT):
        return None

    if not candidate.is_file():
        return None

    try:
        content = candidate.read_text(encoding="utf-8")
        size_bytes = candidate.stat().st_size
    except (OSError, UnicodeDecodeError):
        return None

    return {
        "filename": candidate.name,
        "content": content,
        "size_bytes": size_bytes,
    }


def find_round_archive(
    job: dict[str, Any],
    round_number: int,
) -> Path | None:
    if round_number < 1:
        return None

    summary_path = find_job_summary(job)

    if summary_path is None:
        return None

    summary_root = summary_path.parent.resolve()
    expected_name = f"package_round_{round_number:02d}.tar.gz"

    for candidate in summary_root.rglob(expected_name):
        resolved = candidate.resolve()

        if (
            is_within(resolved, OUTPUT_ROOT)
            and resolved.is_file()
        ):
            return resolved

    return None


# ============================================================
# RESPONSE HELPERS
# ============================================================

def report_download_response(
    report: dict[str, Any],
    filename: str,
):
    safe_filename = re.sub(
        r"[^A-Za-z0-9_.-]",
        "_",
        filename,
    )

    response = make_response(jsonify(report))
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{safe_filename}"'
    )
    response.headers["X-Content-Type-Options"] = "nosniff"

    return response


# ============================================================
# JOB EXECUTION
# ============================================================

def execute_job(
    job_id: str,
    archive: Path,
    method: str,
    resume: bool,
) -> None:
    global current_job

    try:
        with state_lock:
            if current_job and current_job.get("id") == job_id:
                current_job.update(
                    {
                        "status": "RUNNING",
                        "started_at": utc_now(),
                        "updated_at": utc_now(),
                        "phase": "INITIALIZING",
                        "message": "Initializing pipeline...",
                        "progress": None,
                        "current_round": 0,
                        "current_gate": None,
                        "gate_results": {},
                        "progress_error": None,
                    }
                )

        result = run_package(
            archive_path=archive,
            method=method,
            resume=resume,
            progress_callback=lambda event: update_job_progress(
                job_id,
                event,
            ),
        )

        result = json_safe(result)
        pipeline_status = result.get("status", "UNKNOWN")

        if pipeline_status in TERMINAL_STATUSES:
            final_status = pipeline_status
        elif pipeline_status in {"QUEUED", "RUNNING"}:
            final_status = pipeline_status
        else:
            # Unexpected statuses must not be silently called COMPLETED.
            final_status = "ERROR"
            result["status_mapping_warning"] = (
                f"Unexpected pipeline status: {pipeline_status}"
            )

        with state_lock:
            if current_job and current_job.get("id") == job_id:
                current_job.update(
                    {
                        "status": final_status,
                        "finished_at": utc_now(),
                        "updated_at": utc_now(),
                        "result": result,
                        "message": f"Pipeline finished: {pipeline_status}",
                        "phase": "FINISHED",
                    }
                )

    except Exception as exc:
        app.logger.exception(
            "Robustness job %s failed",
            job_id,
        )

        with state_lock:
            if current_job and current_job.get("id") == job_id:
                current_job.update(
                    {
                        "status": "ERROR",
                        "finished_at": utc_now(),
                        "updated_at": utc_now(),
                        "error": str(exc),
                        "message": "The pipeline raised an exception.",
                        "phase": "ERROR",
                    }
                )

    finally:
        # A job owns this lock from create_job until its worker exits.
        if job_lock.locked():
            job_lock.release()


# ============================================================
# ROUTES: DASHBOARD AND HEALTH
# ============================================================

@app.route("/")
def index():
    return send_from_directory(
        app.static_folder,
        "index.html",
    )


@app.get("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "project_root": str(PROJECT_ROOT),
            "malregistry_root": str(MALREGISTRY_ROOT),
            "malregistry_exists": MALREGISTRY_ROOT.is_dir(),
            "output_dir": str(OUTPUT_ROOT),
            "supported_methods": sorted(SUPPORTED_METHODS),
        }
    )


@app.get("/api/malregistry/packages")
def packages():
    if not MALREGISTRY_ROOT.is_dir():
        return jsonify(
            {
                "success": False,
                "error": f"Directory not found: {MALREGISTRY_ROOT}",
                "items": [],
                "packages": [],
                "total": 0,
            }
        ), 500

    query = request.args.get("q", "").strip().casefold()

    try:
        limit = min(
            max(int(request.args.get("limit", 300)), 1),
            1000,
        )
        offset = max(
            int(request.args.get("offset", 0)),
            0,
        )
    except ValueError:
        return jsonify(
            {
                "success": False,
                "error": "limit and offset must be integers",
                "items": [],
                "packages": [],
                "total": 0,
            }
        ), 400

    force_refresh = request.args.get(
        "refresh",
        "",
    ).casefold() in {"1", "true", "yes"}

    items = get_cached_archives(
        force_refresh=force_refresh,
    )

    # Filter by search query first (instant string match)
    if query:
        items = [
            item
            for item in items
            if query in item["package"].casefold()
            or query in item["version"].casefold()
        ]

    linux_only = request.args.get("linux_only", "true").casefold() in {"1", "true", "yes"}

    if not linux_only:
        total = len(items)
        page = items[offset : offset + limit]
    else:
        # Lazily check Linux compatibility only until we fill the requested page
        from pipeline.dysec_client import flush_compat_cache
        page = []
        matched = 0
        for item in items:
            if is_linux_compatible(Path(item["archive"])):
                if matched >= offset and len(page) < limit:
                    page.append(item)
                matched += 1
                # Stop unpacking once we have enough items for the dropdown
                if len(page) >= limit and not query:
                    break
        flush_compat_cache()
        total = matched

    return jsonify(
        {
            "success": True,
            "total": total,
            "count": len(page),
            "items": page,
            "packages": page,
        }
    )


@app.get("/api/robustness/status")
def robustness_status():
    with state_lock:
        if current_job is None:
            return jsonify(
                {
                    "status": "IDLE",
                    "job": None,
                }
            )

        return jsonify(
            {
                "job": json_safe(current_job),
            }
        )


# ============================================================
# ROUTES: ROUND ARTIFACTS
# ============================================================

@app.get("/api/robustness/round/<int:round_number>/artifacts")
def round_artifacts(round_number: int):
    """
    Return allowlisted artifacts for one round.

    Possible keys:
      prompt
      raw_output
      normalized_output
      original_target
      reconstructed_source
      generation_result
      target_scope
      mutation_plan
      mutation_plan_target_validation

    Missing artifacts are omitted. This endpoint does not execute code.
    """
    with state_lock:
        job = dict(current_job) if current_job else None

    if job is None:
        return jsonify(
            {
                "success": False,
                "error": "No pipeline job is available.",
            }
        ), 404

    round_dir = find_round_directory(
        job,
        round_number,
    )

    if round_dir is None:
        return jsonify(
            {
                "success": True,
                "round": round_number,
                "available": False,
                "artifacts": {},
                "message": (
                    "Round artifacts were not found. "
                    "The pipeline may not save them yet."
                ),
            }
        )

    artifacts: dict[str, Any] = {}

    for key, filename in ARTIFACT_FILES.items():
        artifact = read_artifact(
            round_dir,
            filename,
        )

        if artifact is not None:
            artifacts[key] = artifact

    # Convenient aliases for a dashboard code viewer.
    original = artifacts.get("original_target")
    reconstructed = artifacts.get("reconstructed_source")
    normalized = artifacts.get("normalized_output")

    return jsonify(
        {
            "success": True,
            "round": round_number,
            "available": bool(artifacts),
            "artifacts": artifacts,
            "target_code": (
                original["content"]
                if original is not None
                else None
            ),
            "mutated_code": (
                reconstructed["content"]
                if reconstructed is not None
                else (
                    normalized["content"]
                    if normalized is not None
                    else None
                )
            ),
        }
    )


# ============================================================
# ROUTES: REPORTS
# ============================================================

@app.get("/api/reports/summary")
def download_summary_report():
    with state_lock:
        job = dict(current_job) if current_job else None

    if job is None or not job.get("result"):
        return jsonify(
            {
                "success": False,
                "error": "No completed job report is available.",
            }
        ), 404

    summary_path = find_job_summary(job)

    if summary_path is None:
        return jsonify(
            {
                "success": False,
                "error": "Summary report not found for the current job.",
            }
        ), 404

    try:
        report = json.loads(
            summary_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return jsonify(
            {
                "success": False,
                "error": "Unable to read the summary report.",
            }
        ), 500

    filename = (
        f"{report.get('package', 'evaluation')}-summary.json"
    )

    return report_download_response(
        report,
        filename,
    )


@app.get("/api/reports/round/<int:round_number>")
def download_round_report(round_number: int):
    with state_lock:
        job = dict(current_job) if current_job else None

    if job is None or not job.get("result"):
        return jsonify(
            {
                "success": False,
                "error": "No completed job report is available.",
            }
        ), 404

    summary_path = find_job_summary(job)

    if summary_path is None:
        return jsonify(
            {
                "success": False,
                "error": "Summary report not found for the current job.",
            }
        ), 404

    try:
        summary = json.loads(
            summary_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return jsonify(
            {
                "success": False,
                "error": "Unable to read the summary report.",
            }
        ), 500

    round_record = next(
        (
            item
            for item in summary.get("history", [])
            if isinstance(item, dict)
            and str(item.get("round")) == str(round_number)
        ),
        None,
    )

    if round_record is None:
        return jsonify(
            {
                "success": False,
                "error": f"No report exists for round {round_number}.",
            }
        ), 404

    report = {
        "experiment": summary.get("experiment"),
        "package": summary.get("package"),
        "round": round_record,
    }

    filename = (
        f"{summary.get('package', 'evaluation')}"
        f"-round-{round_number:02d}-report.json"
    )

    return report_download_response(
        report,
        filename,
    )


# ============================================================
# ROUTES: START, RESUME, STOP
# ============================================================

@app.post("/api/robustness/start")
def start_robustness():
    return create_job(resume=False)


@app.post("/api/robustness/resume")
def resume_robustness():
    return create_job(resume=True)


@app.post("/api/robustness/stop")
def stop_robustness():
    with state_lock:
        if current_job is None:
            return jsonify(
                {
                    "success": False,
                    "message": "No job exists.",
                }
            ), 409

        status = current_job.get("status")

        if status not in {"QUEUED", "RUNNING"}:
            return jsonify(
                {
                    "success": False,
                    "message": f"Job is not running (status={status}).",
                    "status": status,
                }
            ), 409

        current_job["stop_requested"] = True
        current_job["message"] = (
            "Stop requested. The pipeline must check the cancellation "
            "signal at a safe stopping point."
        )
        current_job["updated_at"] = utc_now()

        return jsonify(
            {
                "success": True,
                "message": current_job["message"],
                "status": current_job["status"],
            }
        ), 202


def create_job(resume: bool):
    global current_job

    payload = request.get_json(silent=True) or {}

    package = str(payload.get("package", "")).strip()
    version = str(payload.get("version", "")).strip()
    method = str(
        payload.get("method", "proposed_feedback")
    ).strip()

    if not package or not version:
        return jsonify(
            {
                "error": "package and version are required.",
            }
        ), 400

    if method not in SUPPORTED_METHODS:
        return jsonify(
            {
                "error": "Unsupported method",
                "supported_methods": sorted(SUPPORTED_METHODS),
            }
        ), 400

    archive = find_archive(
        package,
        version,
    )

    if archive is None:
        return jsonify(
            {
                "error": (
                    f"No archive found for package "
                    f"{package} ({version})."
                ),
            }
        ), 404

    if not job_lock.acquire(blocking=False):
        return jsonify(
            {
                "error": "Another robustness job is already running.",
            }
        ), 409

    job_id = str(uuid.uuid4())

    job = {
        "id": job_id,
        "package": package,
        "version": version,
        "archive": str(archive),
        "method": method,
        "resume": resume,
        "status": "QUEUED",
        "created_at": utc_now(),
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
        "message": "Job created successfully.",
        "phase": "QUEUED",
        "progress": None,
        "current_round": 0,
        "current_gate": None,
        "gate_results": {},
        "progress_error": None,
        "token_usage_by_round": {},
        "updated_at": utc_now(),
        "stop_requested": False,
    }

    with state_lock:
        current_job = job

    try:
        worker = threading.Thread(
            target=execute_job,
            args=(
                job_id,
                archive,
                method,
                resume,
            ),
            daemon=True,
            name=f"dysec-{job_id[:8]}",
        )

        worker.start()

    except Exception:
        with state_lock:
            if current_job and current_job.get("id") == job_id:
                current_job = None

        job_lock.release()
        raise

    return jsonify(
        {
            "job": job,
        }
    ), 202


# ============================================================
# ROUTE: PACKAGE ARCHIVE DOWNLOAD
# ============================================================

@app.get("/api/packages/round/<int:round_number>/download")
def download_round_package(round_number: int):
    with state_lock:
        job = dict(current_job) if current_job else None

    if job is None:
        return jsonify(
            {
                "success": False,
                "error": "No pipeline job is available.",
            }
        ), 404

    if not job.get("result"):
        return jsonify(
            {
                "success": False,
                "error": "The pipeline has not completed yet.",
            }
        ), 409

    archive_path = find_round_archive(
        job,
        round_number,
    )

    if archive_path is None:
        return jsonify(
            {
                "success": False,
                "error": (
                    f"No package archive found for round {round_number}."
                ),
            }
        ), 404

    response = send_file(
        archive_path,
        as_attachment=True,
        download_name=archive_path.name,
        mimetype="application/gzip",
        conditional=True,
        max_age=0,
    )

    response.headers["X-Content-Type-Options"] = "nosniff"

    return response


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    app.run(
        host=os.getenv("DASHBOARD_HOST", "0.0.0.0"),
        port=int(os.getenv("DASHBOARD_PORT", "5000")),
        debug=os.getenv(
            "DASHBOARD_DEBUG",
            "false",
        ).casefold() in {"1", "true", "yes"},
        threaded=True,
    )
