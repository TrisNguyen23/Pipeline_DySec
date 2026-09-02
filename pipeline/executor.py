from pathlib import Path


def execute_and_trace(
    code_path,
    trace_path,
):

    trace_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    trace_path.write_text(
        "syscall_1\n"
        "syscall_2\n"
        "syscall_3\n",
        encoding="utf-8"
    )

    return {
        "success": True,
        "return_code": 0,
        "trace_path": str(trace_path),
        "error": None,
    }