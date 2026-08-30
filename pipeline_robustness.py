import subprocess
import requests
import json
import time
import os
import sys

OLLAMA_API = "http://192.168.25.1:11434/api/generate"
MODEL_NAME = "qwen2.5-coder:3b"

OUTPUT_DIR = "output_data/robustness_test"
os.makedirs(OUTPUT_DIR, exist_ok=True)

INITIAL_CODE = """
import os
import tempfile
import socket

def execute_system_tasks():
    temp_file = os.path.join(tempfile.gettempdir(), "audit_metric.log")
    with open(temp_file, "w") as f:
        f.write("Status: OK\\n")
    
    with open(temp_file, "r") as f:
        data = f.read()
        
    if os.path.exists(temp_file):
        os.remove(temp_file)

    host = socket.gethostname()
    return len(data), host

if __name__ == "__main__":
    execute_system_tasks()
"""

def request_code_refactoring(source_code, iteration):
    prompt = f"""
You are an automated software refactoring tool for academic robustness evaluation.
Refactor the following Python code snippet by applying standard transformations (e.g., dynamic imports, function encapsulation, alias renaming) while strictly preserving its original runtime behavior and side effects.

Return ONLY raw, valid, executable Python code. Do not include markdown code fences, comments, or explanations.

Source Code:
{source_code}
"""
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3
        }
    }
    
    try:
        response = requests.post(OLLAMA_API, json=payload, timeout=60)
        res_json = response.json()
        generated_code = res_json.get("response", "").strip()
        cleaned_code = generated_code.replace("```python", "").replace("```", "").strip()
        return cleaned_code
    except Exception as e:
        print(f"[-] Error calling Ollama API: {e}")
        return source_code

def trace_execution(code_path, trace_output_path):
    trace_cmd = (
        f"sudo bpftrace -o {trace_output_path} "
        f"-e 'tracepoint:raw_syscalls:sys_enter /pid == cpid/ {{ printf(\"%s\\n\", probe); }}' "
        f"-c 'python3 {code_path}'"
    )
    subprocess.run(trace_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def evaluate_with_dysec(trace_path):
    result = subprocess.run(
        f"python3 run_predict.py {trace_path}",
        shell=True,
        capture_output=True,
        text=True
    )
    return result.stdout

def run_pipeline(max_iterations=5):
    current_code = INITIAL_CODE
    print("=" * 65)
    print("      DYSEC: AUTOMATED ROBUSTNESS EVALUATION PIPELINE")
    print("=" * 65)

    for i in range(1, max_iterations + 1):
        print(f"\n>>> [ITERATION {i}/{max_iterations}] <<<")
        
        if i > 1:
            print("[1] Requesting code refactoring from Local LLM...")
            current_code = request_code_refactoring(current_code, i)
        
        code_file = os.path.join(OUTPUT_DIR, f"variant_v{i}.py")
        with open(code_file, "w") as f:
            f.write(current_code)
        print(f"[+] Saved code variant: {code_file}")

        trace_file = os.path.join(OUTPUT_DIR, f"trace_v{i}.trace")
        print(f"[2] Starting Sandbox & Tracing Syscalls...")
        trace_execution(code_file, trace_file)
        
        event_count = 0
        if os.path.exists(trace_file):
            with open(trace_file, "r") as f:
                event_count = sum(1 for _ in f)
        print(f"[+] Captured {event_count:,} Syscall events into: {trace_file}")

        print(f"[3] Evaluating Syscall trace with DySec model...")
        model_output = evaluate_with_dysec(trace_file)
        print(model_output)

if __name__ == "__main__":
    run_pipeline()