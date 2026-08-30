# Pipeline_DySec

# Automated Robustness Evaluation Pipeline for DySec

An automated evaluation framework for empirically testing the robustness of **DySec**, a dynamic syscall-based intrusion detection system, against **semantics-preserving code transformations**.

The pipeline combines a local Large Language Model (LLM), an isolated Ubuntu sandbox, eBPF-based syscall tracing, and the pre-trained DySec Random Forest classifier to evaluate whether transformed programs remain detectable.

---

## Overview

The pipeline follows this workflow:

```text
┌─────────────────────┐
│    LLM Engine       │
│      Ollama         │
│     qwen3:8b        │
└──────────┬──────────┘
           │ HTTP API
           ▼
┌─────────────────────┐
│  Code Transformer   │
│                     │
│ Generate semantic-  │
│ preserving variants │
└──────────┬──────────┘
           │
           │ Generated Variants
           ▼
┌──────────────────────────────────┐
│        Ubuntu Sandbox            │
│                                  │
│  ┌────────────────────────────┐  │
│  │ Execute transformed code   │  │
│  └──────────────┬─────────────┘  │
│                 │                │
│                 ▼                │
│  ┌────────────────────────────┐  │
│  │ eBPF / bpftrace             │  │
│  │ Syscall collection          │  │
│  └──────────────┬─────────────┘  │
│                 │                │
│                 ▼                │
│             .trace              │
└─────────────────┬────────────────┘
                  │
                  ▼
        ┌─────────────────────┐
        │   DySec Inference   │
        │                     │
        │ Random Forest Model  │
        │ + syscall n-grams   │
        └──────────┬──────────┘
                   │
                   ▼
             ┌─────────────┐
             │   Verdict    │
             │             │
             │ Benign /    │
             │ Malicious   │
             └─────────────┘
```

---

# Research Objective

The primary objective of this pipeline is to evaluate whether **DySec remains robust against semantic-preserving transformations of executable code**.

A program is transformed while attempting to preserve its original behaviour. The transformed variant is then executed in the sandbox, and its syscall behaviour is collected.

The resulting syscall trace is passed through the DySec detection pipeline.

Conceptually:

```text
Original Program
       │
       ▼
Semantic-Preserving Transformation
       │
       ▼
Transformed Variant
       │
       ▼
Sandbox Execution
       │
       ▼
Syscall Trace
       │
       ▼
n-gram Feature Extraction
       │
       ▼
DySec Random Forest
       │
       ▼
Prediction
```

This allows the detection performance of DySec to be compared between the original and transformed versions of a program.

---

# Architecture

The system consists of four major components.

## 1. LLM Engine

The LLM engine runs locally using **Ollama** and the `qwen3:8b` model.

Its role is to generate code variants according to the transformation instructions provided by the evaluation pipeline.

```text
pipeline_robustness.py
        │
        │ HTTP request
        ▼
Ollama API
        │
        ▼
qwen3:8b
        │
        ▼
Transformed Python Code
```

---

## 2. Code Transformation

The code transformer generates variants of the original program while attempting to preserve its semantics.

Each generated variant is stored independently so that its source code can be inspected and reproduced.

Example:

```text
Original
   │
   ├──> Variant 1
   ├──> Variant 2
   ├──> Variant 3
   └──> Variant N
```

---

## 3. Ubuntu Sandbox

Generated variants are executed inside an isolated Ubuntu environment.

The sandbox is responsible for:

- Executing transformed programs
- Collecting syscall events
- Producing `.trace` files
- Running DySec inference

Syscalls are collected using:

```text
tracepoint:raw_syscalls:sys_enter
```

through `bpftrace`.

---

## 4. DySec Classifier

The collected syscall traces are evaluated using the pre-trained DySec Random Forest model:

```text
RF_best_model_ngrams.pkl
```

The model uses syscall **n-gram features** as its input representation.

```text
.trace
  │
  ▼
Syscall Sequence
  │
  ▼
n-gram Extraction
  │
  ▼
Feature Vector
  │
  ▼
Random Forest
  │
  ▼
Prediction
```

---

# Requirements

## Host Machine

The host machine runs the LLM service.

Required:

- Ollama
- `qwen3:8b`
- Network connectivity to the Ubuntu VM

---

## Ubuntu Sandbox

The Ubuntu VM requires:

- Ubuntu Linux
- Python 3
- Python `pip`
- `bpftrace`
- `joblib`
- `numpy`
- `scikit-learn`
- `requests`

The sandbox should be isolated from the host environment because generated code is executed automatically.

---

# Installation

## 1. Install Ubuntu Dependencies

Inside the Ubuntu VM:

```bash
sudo apt update
sudo apt install -y bpftrace python3 python3-pip
```

Install the required Python packages:

```bash
pip3 install joblib numpy scikit-learn requests
```

If the system does not allow global `pip` installation, use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install joblib numpy scikit-learn requests
```

---

# Ollama Setup

## 1. Install Ollama

Install Ollama on the host machine.

Verify the installation:

```bash
ollama --version
```

---

## 2. Pull the LLM

Download the required model:

```bash
ollama pull qwen3:8b
```

Verify that the model is available:

```bash
ollama list
```

The output should include:

```text
qwen3:8b
```

---

## 3. Start the Ollama Server

Ollama must listen on an interface that is reachable from the Ubuntu VM.

### Linux

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

### Windows PowerShell

```powershell
$env:OLLAMA_HOST="0.0.0.0:11434"
ollama serve
```

The default Ollama API port is:

```text
11434
```

Keep the Ollama server running while the robustness evaluation is in progress.

---

# Network Configuration

The Ubuntu VM must be able to communicate with the host machine running Ollama.

The host IP address depends on the VM networking configuration.

Do **not** hard-code a host IP in the pipeline documentation. Instead, replace:

```text
<HOST_IP>
```

with the appropriate IP address for your environment.

From the Ubuntu VM, test the Ollama connection:

```bash
curl http://<HOST_IP>:11434/api/tags
```

A successful response should contain the available Ollama models.

For example:

```json
{
  "models": [
    {
      "name": "qwen3:8b"
    }
  ]
}
```

If the connection fails, check:

1. Ollama is running on the host.
2. Ollama is listening on `0.0.0.0`.
3. TCP port `11434` is accessible.
4. The Ubuntu VM can reach the host.
5. `<HOST_IP>` is the correct address for the host from the VM.
6. Host firewall rules are not blocking the connection.

---

# Directory Structure

The repository is organised as follows:

```text
.
├── pipeline_robustness.py
├── run_predict.py
│
├── input_data/
│   └── ...
│
└── output_data/
    └── robustness_test/
        ├── variant_v1.py
        ├── trace_v1.trace
        ├── variant_v2.py
        ├── trace_v2.trace
        ├── variant_v3.py
        ├── trace_v3.trace
        └── ...
```

## Main Components

### `pipeline_robustness.py`

The main orchestration script.

It coordinates the complete robustness evaluation pipeline:

1. Load the input program.
2. Request a transformation from the LLM.
3. Generate a transformed variant.
4. Execute the variant inside the sandbox.
5. Collect syscall events.
6. Save the syscall trace.
7. Run DySec inference.
8. Report the prediction results.

---

### `run_predict.py`

Runs DySec inference on a syscall trace.

It loads the pre-trained Random Forest model and evaluates the extracted syscall n-gram features.

---

### `input_data/`

Contains the source programs or package benchmarks used in the experiments.

Example:

```text
input_data/
├── sample_1.py
├── sample_2.py
└── ...
```

---

### `output_data/`

Contains all generated experimental artifacts.

```text
output_data/
└── robustness_test/
```

Generated variants and syscall traces are stored here.

---

# DySec Model

The pipeline uses the pre-trained DySec Random Forest model:

```text
RF_best_model_ngrams.pkl
```

The model expects syscall n-gram features extracted from the collected trace.

The inference process is:

```text
Raw Syscall Trace
       │
       ▼
Syscall Sequence
       │
       ▼
n-gram Feature Extraction
       │
       ▼
Feature Vector
       │
       ▼
RF_best_model_ngrams.pkl
       │
       ▼
Prediction
```

Ensure that the model path configured in the inference script points to the correct `.pkl` file.

---

# Running the Pipeline

## Step 1 — Start Ollama

On the host machine:

```bash
ollama pull qwen3:8b
```

Then start the server:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

---

## Step 2 — Verify Connectivity

From the Ubuntu VM:

```bash
curl http://<HOST_IP>:11434/api/tags
```

Confirm that `qwen3:8b` is available.

---

## Step 3 — Run the Robustness Evaluation

From the Ubuntu sandbox:

```bash
sudo python3 pipeline_robustness.py
```

Elevated privileges are required because the pipeline uses `bpftrace` to access kernel syscall events.

---

# Output

After execution, generated artifacts are stored in:

```text
output_data/robustness_test/
```

A typical directory may contain:

```text
output_data/
└── robustness_test/
    ├── variant_v1.py
    ├── trace_v1.trace
    ├── variant_v2.py
    ├── trace_v2.trace
    ├── variant_v3.py
    ├── trace_v3.trace
    └── ...
```

## Transformed Variants

Files following this format:

```text
variant_vX.py
```

contain the source code generated by the LLM.

Each variant corresponds to one transformation attempt.

---

## Syscall Traces

Files following this format:

```text
trace_vX.trace
```

contain the syscall events collected during execution.

The variant-to-trace relationship is:

```text
variant_v1.py  ───>  trace_v1.trace
variant_v2.py  ───>  trace_v2.trace
variant_v3.py  ───>  trace_v3.trace
       ...
```

---

# Evaluation

For every transformed variant, the pipeline produces a DySec prediction.

The evaluation can be represented as:

```text
Variant
   │
   ├── Source Code
   │
   ├── Transformation
   │
   ├── Execution
   │
   ├── Syscall Trace
   │
   └── DySec Prediction
             │
             ▼
       Benign / Malicious
```

The predictions can then be compared with the expected labels.

Useful evaluation metrics include:

- Detection Rate
- False-Negative Rate
- Evasion Rate
- Detection Rate Before Transformation
- Detection Rate After Transformation
- Per-Transformation Detection Rate

---

# Evasion Rate

For malicious samples, an important metric is the **evasion rate**.

It measures the proportion of transformed malicious variants that DySec incorrectly classifies as benign.

```text
                    Number of transformed malicious
                    variants classified as benign
Evasion Rate = ─────────────────────────────────────────
                Total number of transformed malicious
                         variants
```

A higher evasion rate indicates that the detector is more vulnerable to the evaluated transformations.

Conversely, a lower evasion rate indicates greater robustness.

---

# Reproduction

The complete experiment can be reproduced using the following procedure.

## 1. Prepare the Ubuntu Sandbox

```bash
sudo apt update
sudo apt install -y bpftrace python3 python3-pip
```

Install Python dependencies:

```bash
pip3 install joblib numpy scikit-learn requests
```

---

## 2. Prepare Ollama

On the host:

```bash
ollama pull qwen3:8b
```

Start the server:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

---

## 3. Configure Host Connectivity

From Ubuntu:

```bash
curl http://<HOST_IP>:11434/api/tags
```

Verify that the Ollama API is reachable and `qwen3:8b` is available.

---

## 4. Run the Experiment

```bash
sudo python3 pipeline_robustness.py
```

---

## 5. Inspect the Results

```bash
ls -lh output_data/robustness_test/
```

Inspect a generated variant:

```bash
cat output_data/robustness_test/variant_v1.py
```

Inspect its corresponding syscall trace:

```bash
cat output_data/robustness_test/trace_v1.trace
```

---

# Troubleshooting

## Ollama Connection Refused

If you receive:

```text
Connection refused
```

make sure Ollama is running:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Then test from Ubuntu:

```bash
curl http://<HOST_IP>:11434/api/tags
```

---

## `bpftrace` Permission Error

If the pipeline cannot attach to the syscall tracepoint, run:

```bash
sudo python3 pipeline_robustness.py
```

You can also test `bpftrace` independently:

```bash
sudo bpftrace -e 'tracepoint:raw_syscalls:sys_enter { printf("%s\n", comm); }'
```

Stop the test using:

```text
Ctrl+C
```

---

## Python Import Error

Check the installed packages:

```bash
pip3 list
```

Install the required dependencies:

```bash
pip3 install joblib numpy scikit-learn requests
```

---

## DySec Model Not Found

If inference reports that the model cannot be found, verify the path to:

```text
RF_best_model_ngrams.pkl
```

Make sure the file is accessible from the environment where `run_predict.py` is executed.

---

## No Trace Generated

If a `.trace` file is not generated, check:

1. `bpftrace` is installed.
2. The pipeline is running with sufficient privileges.
3. The target program executes successfully.
4. The syscall tracepoint is available.
5. The output directory exists and is writable.

---

# Security Considerations

This pipeline executes **LLM-generated code** automatically.

For this reason, experiments should be performed inside an isolated and disposable environment.

Recommended precautions:

- Run generated code only inside the Ubuntu VM.
- Do not execute generated variants directly on the host.
- Avoid mounting sensitive host directories into the VM.
- Restrict unnecessary network access from the sandbox.
- Do not expose the Ollama API to untrusted external networks.
- Use VM snapshots so that experiments can be reset easily.
- Do not place sensitive credentials or private files inside the sandbox.

The Ubuntu VM should be considered an **untrusted code execution environment**.

---

# Experimental Workflow

The complete workflow is:

```text
                         ┌──────────────────┐
                         │  Original Sample │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │  LLM Transformer │
                         │     qwen3:8b     │
                         └────────┬─────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
               Variant 1     Variant 2     Variant N
                    │             │             │
                    └─────────────┼─────────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ Ubuntu Sandbox   │
                         │    Execution     │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ eBPF / bpftrace  │
                         │ Syscall Tracing  │
                         └────────┬─────────┘
                                  │
                                  ▼
                              .trace
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ n-gram Features  │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ DySec RF Model   │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ Detection Result │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ Robustness /     │
                         │ Evasion Metrics  │
                         └──────────────────┘
```

---

# Reproducibility Checklist

Before running an experiment, verify the following:

- [ ] Ubuntu VM is running.
- [ ] `bpftrace` is installed.
- [ ] Python dependencies are installed.
- [ ] DySec Random Forest model is available.
- [ ] Ollama is installed on the host.
- [ ] `qwen3:8b` has been downloaded.
- [ ] Ollama is listening on port `11434`.
- [ ] Ubuntu can reach `<HOST_IP>:11434`.
- [ ] `input_data/` contains the required benchmark programs.
- [ ] The output directory is writable.
- [ ] The experiment is executed inside an isolated environment.

---

# Project Status

This repository provides an experimental pipeline for evaluating the robustness of DySec against semantics-preserving program transformations.

The framework is intended for:

- Security research
- Intrusion detection evaluation
- Adversarial robustness experiments
- Syscall-based malware detection research
- Reproducible empirical evaluation

---

# Citation

If this repository or its results are used in academic work, please cite the original **DySec** research and the associated dataset/model used in the experiments.

---

# License

Add the appropriate license for this repository.

For example:

```text
MIT License
```

if the repository is released under the MIT License.
