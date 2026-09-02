import os
import tempfile
import socket


def execute_system_tasks():
    temp_file = os.path.join(
        tempfile.gettempdir(),
        "audit_metric.log"
    )

    with open(temp_file, "w") as f:
        f.write("Status: OK\n")

    with open(temp_file, "r") as f:
        data = f.read()

    if os.path.exists(temp_file):
        os.remove(temp_file)

    host = socket.gethostname()

    return len(data), host


if __name__ == "__main__":
    execute_system_tasks()