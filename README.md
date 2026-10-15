# Pipeline_DySec

**An LLM-driven pipeline for iterative Python package mutation, validation, and detector robustness evaluation.**

Pipeline_DySec is a research prototype designed to study how large language models (LLMs) can generate source-code variants of Python packages and how those variants perform under a structured validation and detector-evaluation workflow.

The pipeline combines AST-based target selection, LLM-guided code transformation, multi-stage validation, package-level artifact management, and DySec evaluation. It supports multiple mutation strategies and records experiment state to facilitate analysis and reproducibility.

> **Research scope:** Pipeline_DySec evaluates generated variants under a defined execution environment and detector configuration. Passing syntax or installation validation does not establish full semantic equivalence, software safety, or robustness against other detectors.

## Table of Contents

- [Overview](#overview)
- [Research Objectives](#research-objectives)
- [Pipeline Architecture](#pipeline-architecture)
- [Mutation Strategies](#mutation-strategies)
- [Repository Structure](#repository-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Input Dataset](#input-dataset)
- [Running Experiments](#running-experiments)
- [DySec Evaluation](#dysec-evaluation)
- [Outputs and Artifacts](#outputs-and-artifacts)
- [Evaluation Metrics](#evaluation-metrics)
- [Reproducibility](#reproducibility)
- [Limitations](#limitations)
- [Responsible Use](#responsible-use)

## Overview

The objective of Pipeline_DySec is to provide an experimental framework for investigating the feasibility, validation robustness, and detector outcomes of LLM-generated Python package variants.

The pipeline separates package transformation from validation and detector evaluation. This separation makes it possible to investigate where candidate variants fail, how mutation strategies differ, and whether generated variants receive a valid detector verdict.

The main components are:

- **AST-based target selection:** identifies eligible Python functions, classes, and module-level code blocks.
- **LLM-based generation:** generates transformed source code using an Ollama-compatible inference endpoint.
- **Validation gates:** check generated output and package-level acceptance conditions.
- **Iterative experiment management:** tracks mutation rounds, artifacts, experiment history, and pending evaluations.
- **DySec integration:** submits eligible package archives for detector evaluation or supports a manual/pending workflow.
- **Experiment reporting:** aggregates package-level results into a CSV summary.

## Research Objectives

Pipeline_DySec is designed to support investigations into the following questions.

### RQ1 — Generation Feasibility and Validation Robustness

How reliably can the pipeline generate Python package variants that satisfy the defined validation gates?

Potential measurements include generation success rate, per-gate pass rate, end-to-end validation rate, and failure-reason distribution.

### RQ2 — Mutation Strategy Effectiveness

How do different mutation strategies affect the generation and validation of package variants?

This investigation can compare random selection, function-level mutation, proposed target-selection strategies, and feedback-guided mutation under consistent experimental conditions.

### RQ3 — Detector Outcomes

What detector outcomes are observed for validated variants under the configured DySec evaluation conditions?

Detection outcomes must be calculated only from valid detector verdicts. Pending evaluations, API errors, and invalid responses must be reported separately.

### RQ4 — Generation Cost and Efficiency

What computational and generation costs are associated with producing validated variants?

Where telemetry is available, useful measurements include LLM latency, token usage, attempts per validated variant, and time required to obtain a valid detector verdict.

These questions describe potential evaluation objectives, not claims that any particular result has already been achieved.

## Pipeline Architecture

The high-level workflow is:

```text
Input Python Package Archive
            |
            v
    Package Initialization
            |
            v
   Platform Compatibility Check
            |
            v
      Source and AST Analysis
            |
            v
  Target and Mutation Selection
            |
            v
      LLM-Based Generation
            |
            v
      Generated-Code Checks
            |
            v
   Source and Structural Guards
            |
            v
       Diversity Analysis
            |
            v
  Package Installation Validation
            |
            v
    Candidate Package Archive
            |
            v
       DySec Evaluation
            |
            v
   Verdict and Artifact Recording
            |
            v
      Experiment Summary
```

The workflow is iterative. The pipeline records round state and artifacts, and its control flow determines whether another round can proceed or must wait for a pending detector evaluation.

### Validation and evaluation are different

Pipeline_DySec distinguishes internal candidate validation from detector evaluation.

- **Generation success:** the LLM produces a usable candidate.
- **Validation success:** the candidate satisfies the applicable internal gates.
- **Evaluation completion:** a valid detector verdict is obtained.
- **Detector outcome:** the returned verdict indicates detection or non-detection under the configured conditions.

These states should not be treated as interchangeable. In particular, a package that installs successfully has not necessarily preserved the original package's behavior.

## Mutation Strategies

The experiment configuration defines the following methods:

| Method                  | Intended role                                                                 |
| ----------------------- | ----------------------------------------------------------------------------- |
| `random`                | Randomized target and transformation selection                                |
| `function_level`        | Function-level mutation strategy                                              |
| `proposed`              | Proposed structured mutation workflow                                         |
| `proposed_feedback`     | Proposed workflow incorporating detector feedback                             |
| `strategy_substitution` | Instruction-substitution-focused strategy                                     |
| `strategy_flattening`   | Control-flow-flattening-focused strategy                                      |
| `strategy_encryption`   | Polymorphic-encryption-focused strategy                                       |
| `strategy_opaque`       | Opaque-predicate-focused strategy                                             |
| `proposed_heavy`        | Additional proposed-method variant with a more specific transformation policy |

The available methods and their implementation details are defined in `config/settings.py` and `pipeline/loop.py`.

The batch command-line interface currently exposes `proposed` and `function_level` through the `--method` argument. The presence of additional methods in the experiment configuration does not automatically mean they are selectable through that CLI.

### Transformation families

The pipeline defines the following transformation names:

- `instruction_substitution`
- `control_flow_flattening`
- `polymorphic_encryption`
- `opaque_predicates`
- `dead_code_insertion`
- `optimize`
- `harden`
- `refactor`

Not every transformation is applicable to every target type. The mutation planner and validation logic determine which candidates can be considered.

## Repository Structure

```text
Pipeline_DySec/
├── config/
│   └── settings.py
├── dashboard/
├── dashboard_api/
│   └── app.py
├── models/
│   └── rf/
├── packages/
│   └── Malicious Packages/
├── pipeline/
│   ├── loop.py
│   ├── generator.py
│   ├── mutation_planner.py
│   ├── function_selector.py
│   ├── prompt_builder.py
│   ├── package_loader.py
│   ├── validator.py
│   ├── source_guard.py
│   ├── diversity_checker.py
│   ├── platform_check.py
│   └── dysec_client.py
├── run_demo.py
├── run_predict.py
├── run_robustness.py
├── test.py
└── test_pipeline.py
```

Key files:

| File                            | Responsibility                                                                         |
| ------------------------------- | -------------------------------------------------------------------------------------- |
| `config/settings.py`            | Experiment settings, input/output paths, model configuration, and default round budget |
| `pipeline/loop.py`              | Main experiment orchestration, round management, validation, and artifact recording    |
| `pipeline/mutation_planner.py`  | Mutation-plan construction and transformation selection                                |
| `pipeline/function_selector.py` | Source and structural target discovery                                                 |
| `pipeline/prompt_builder.py`    | Prompt construction for LLM-based generation                                           |
| `pipeline/generator.py`         | Ollama-compatible LLM requests and generation telemetry                                |
| `pipeline/validator.py`         | Package-level installation/execution validation                                        |
| `pipeline/source_guard.py`      | Source-change validation                                                               |
| `pipeline/diversity_checker.py` | Candidate diversity analysis                                                           |
| `pipeline/platform_check.py`    | Platform-scope checks                                                                  |
| `pipeline/dysec_client.py`      | DySec communication and verdict normalization                                          |
| `run_robustness.py`             | Batch package robustness experiments                                                   |
| `run_demo.py`                   | Single-package experiment entry point                                                  |
| `run_predict.py`                | Inference using the configured pretrained Random Forest artifacts                      |
| `dashboard_api/app.py`          | Flask API for dashboard and experiment interaction                                     |
| `dashboard/`                    | Dashboard frontend assets                                                              |

## Requirements

The core pipeline uses Python and an Ollama-compatible generation service.

Recommended environment:

- Linux, for compatibility with the configured validation and monitoring workflow.
- Python 3.10 or later.
- Ollama with the configured model available locally or at a reachable endpoint.
- Network access to DySec when automatic detector evaluation is enabled.
- Python dependencies required by the selected entry point.

The dashboard API additionally uses Flask and Flask-CORS. The pretrained inference entry point may require `pandas`, `joblib`, `scipy`, and `scikit-learn`, depending on the model artifacts and feature-processing implementation.

Use a dedicated virtual environment and pin tested dependency versions before conducting published experiments. If a dependency manifest is added to the repository, use it as the authoritative installation specification.

## Installation

Clone the repository:

```bash
git clone https://github.com/TrisNguyen23/Pipeline_DySec.git
cd Pipeline_DySec
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Upgrade `pip`:

```bash
python -m pip install --upgrade pip
```

Install the dependencies required by your checkout. For the core pipeline and dashboard, the directly used packages include:

```bash
python -m pip install requests flask flask-cors
```

For pretrained Random Forest inference, install the compatible dependencies required by `run_predict.py`:

```bash
python -m pip install pandas joblib scipy scikit-learn
```

The commands above cover the dependencies identified in the main entry points; they are not a substitute for a complete, version-pinned dependency file.

### Configure Ollama

Install Ollama by following the official instructions:

https://ollama.com/

Pull the model configured for your experiment. The current generator defaults to:

```bash
ollama pull huihui_ai/qwen3-abliterated:14b-v2
```

Make sure the Ollama service is running and reachable from the machine executing the pipeline.

The generator's default endpoint is:

```text
http://localhost:11434/api/generate
```

If Ollama runs on another host, set the endpoint accordingly.

## Configuration

Experiment configuration is primarily defined in `config/settings.py`. The generator and DySec client also read environment variables directly.

### Experiment settings

| Setting              | Default                            | Description                             |
| -------------------- | ---------------------------------- | --------------------------------------- |
| `EXPERIMENT_NAME`    | `dysec_progressive_llm_robustness` | Experiment identifier                   |
| `EXPERIMENT_ROUNDS`  | `15`                               | Configured round budget                 |
| `EXPERIMENT_SEED`    | `42`                               | Seed for deterministic random selection |
| `EXPERIMENT_METHODS` | Defined in `config/settings.py`    | Registered experiment methods           |
| `PROMPT_VERSION`     | `v2`                               | Prompt version identifier               |
| `VALIDATION_TYPE`    | `installation`                     | Configured validation type              |
| `PACKAGES_DIR`       | `packages/Malicious Packages`      | Default batch input directory           |
| `OUTPUT_DIR`         | `output_data/robustness_test`      | Root output directory                   |

The round budget is a configuration value, not a guarantee that every package will complete that many evaluated rounds. Validation failures, pending detector results, and experiment-control conditions can affect the number of completed evaluations.

### LLM settings

The generator reads the following environment variables:

| Variable             | Default                               | Purpose                                                   |
| -------------------- | ------------------------------------- | --------------------------------------------------------- |
| `OLLAMA_API_URL`     | `http://localhost:11434/api/generate` | Generation endpoint                                       |
| `LLM_MODEL_NAME`     | `huihui_ai/qwen3-abliterated:14b-v2`  | Generation model                                          |
| `LLM_TEMPERATURE`    | `0.0`                                 | Generation temperature                                    |
| `QWEN_THINKING_MODE` | `false`                               | Enable or disable the generator's thinking-mode directive |

The settings module also defines model and timeout-related parameters. Verify the effective configuration used by the generator before each experiment, because the generator reads its own environment-variable names.

Example:

```bash
export OLLAMA_API_URL="http://localhost:11434/api/generate"
export LLM_MODEL_NAME="huihui_ai/qwen3-abliterated:14b-v2"
export LLM_TEMPERATURE="0.0"
export QWEN_THINKING_MODE="false"
```

### DySec settings

The DySec client reads:

| Variable        | Default                        | Purpose                                  |
| --------------- | ------------------------------ | ---------------------------------------- |
| `DYSEC_API_URL` | `https://api.dysec.io/v1/scan` | Detector API endpoint                    |
| `DYSEC_API_KEY` | Empty                          | Optional bearer-token credential         |
| `DYSEC_MODE`    | `auto`                         | Use `manual` to leave evaluation pending |

Configure automatic evaluation as needed:

```bash
export DYSEC_API_URL="https://api.dysec.io/v1/scan"
export DYSEC_API_KEY="YOUR_DYSEC_API_KEY"
```

To enable manual/pending evaluation:

```bash
export DYSEC_MODE="manual"
```

Never commit API keys or other credentials to source control.

## Input Dataset

The batch runner discovers `.tar.gz` archives recursively under the configured `PACKAGES_DIR`.

By default, the directory is:

```text
packages/
└── Malicious Packages/
    ├── package_a.tar.gz
    └── package_b.tar.gz
```

Each archive should contain a valid Python package source tree that the package loader can extract and inspect.

Before an experiment:

1. Confirm that the configured input directory exists.
2. Verify that the archives are readable.
3. Record the source package version and archive hash.
4. Ensure that the package is appropriate for the selected Linux validation environment.
5. Use only packages that you are authorized to analyze.

The pipeline performs a platform compatibility check before mutation. Packages classified as incompatible may be excluded before mutation rounds begin.

## Running Experiments

### 1. Run the batch robustness pipeline

Run the default proposed method:

```bash
python run_robustness.py
```

Run the function-level baseline:

```bash
python run_robustness.py --method function_level
```

Run only one package, using its archive basename without `.tar.gz`:

```bash
python run_robustness.py --package package_a
```

Limit the experiment to the first package discovered:

```bash
python run_robustness.py --limit 1
```

Combine the options:

```bash
python run_robustness.py \
  --method proposed \
  --package package_a \
  --limit 1
```

Inspect the available command-line options:

```bash
python run_robustness.py --help
```

### 2. Run a single-package demonstration

```bash
python run_demo.py "packages/Malicious Packages/package_a.tar.gz"
```

The demonstration prints the resulting package-level status and other fields returned by the pipeline.

### 3. Resume an experiment

If an experiment requires manual DySec feedback, record the feedback using the artifact format expected by the pipeline and resume the package:

```bash
python run_robustness.py --package package_a --resume
```

Resume behavior depends on the saved experiment state and the pending-round logic. Inspect the saved summary and round artifacts before resuming to ensure that the intended experiment is being continued.

### 4. Run pretrained inference

`run_predict.py` is a separate entry point for Random Forest inference. Consult its argument parser and expected feature schema before running it:

```bash
python run_predict.py --help
```

Use the model artifacts and feature schema that belong to the same training run. Do not combine incompatible preprocessing artifacts and model files.

## DySec Evaluation

The DySec client submits package archives to the configured endpoint in automatic mode and normalizes the response into detector outcomes.

The pipeline distinguishes the following outcomes:

- **`NOT_DETECTED`:** the detector response indicates that the variant was not detected under the configured evaluation conditions.
- **`DETECTED`:** the detector response indicates detection.
- **`AWAITING_DYSEC`:** no valid verdict is currently available, including manual evaluation or a request failure.

A pending result is not evidence of successful evasion. API errors, timeouts, malformed responses, and missing verdicts should be investigated and reported separately from valid detector outcomes.

A non-detection result applies only to the detector and conditions used in the experiment. It does not demonstrate that a variant is safe or undetectable by other security systems.

## Outputs and Artifacts

The default output root is:

```text
output_data/robustness_test/
```

The batch runner writes its package-level CSV summary to:

```text
output_data/robustness_test/overall_results.csv
```

The pipeline also maintains generated variants, validation artifacts, experiment summaries, round history, and logs under the configured output structure.

For each experiment, retain the following information where available:

- Original package archive and cryptographic hash.
- Generated variant and its hash.
- Package name and version.
- Mutation method, target type, target identifier, and transformation.
- Round number and experiment seed.
- Prompt version and effective model configuration.
- Individual validation-gate results and rejection reasons.
- LLM latency and token telemetry.
- Raw detector response, normalized verdict, and API errors.
- Operating system, Python version, and dependency versions.

These records help distinguish a generation failure from a validation failure or an incomplete detector evaluation.

## Evaluation Metrics

Evaluation should separate generation, validation, diversity, detector outcomes, and computational cost.

### Generation and validation

| Metric                     | Definition                                                                                      |
| -------------------------- | ----------------------------------------------------------------------------------------------- |
| Generation Success Rate    | Successful candidate generations divided by the number of generation attempts                   |
| Per-Gate Pass Rate         | Candidates passing a particular gate divided by candidates that reached that gate               |
| End-to-End Validation Rate | Candidates passing all required internal gates divided by the total number of mutation attempts |
| Failure Distribution       | Counts or proportions of attempts rejected at each gate                                         |

### Diversity

| Metric                      | Definition                                                                                       |
| --------------------------- | ------------------------------------------------------------------------------------------------ |
| Unique Variant Rate         | Unique generated variants divided by all generated variants, under a stated uniqueness criterion |
| Duplicate Rate              | Repeated variants divided by all generated variants                                              |
| Transformation Distribution | Frequency of each transformation among recorded attempts                                         |

The exact uniqueness criterion should be documented. A source hash detects byte-identical output, while semantic equivalence requires a stronger method.

### Detector outcomes

| Metric              | Definition                                                                         |
| ------------------- | ---------------------------------------------------------------------------------- |
| Evaluation Coverage | Validated variants receiving valid detector verdicts divided by validated variants |
| Detection Rate      | Detected variants divided by variants with valid detector verdicts                 |
| Non-Detection Rate  | Non-detected variants divided by variants with valid detector verdicts             |

Report pending evaluations and API errors separately. Always state the denominator and the number of valid verdicts.

### Generation cost

Where telemetry is available, report:

- Mean and median generation latency.
- Prompt and completion token usage.
- Attempts required per validated variant.
- Cost or elapsed time per valid detector outcome.

When comparing methods, use consistent package sets, evaluation conditions, and resource budgets. Multiple rounds for the same package should not automatically be treated as independent observations.

## Reproducibility

The pipeline uses a configured experiment seed for deterministic random selection. However, an identical seed does not guarantee identical generated code from a nondeterministic LLM service.

For reproducible research, record:

1. Repository commit or release identifier.
2. Input package hashes and package versions.
3. Python, operating-system, and dependency versions.
4. Experiment method, seed, round budget, and prompt version.
5. Effective model name and generation parameters.
6. Validation settings and detector configuration.
7. Raw outputs, round history, artifacts, and detector responses.
8. Pending or failed evaluations and the way they were handled.

Keep the experiment budget and stopping policy consistent across methods. Do not silently exclude failed attempts or pending results from reported statistics.

## Limitations

Pipeline_DySec is an evolving research prototype. Its results should be interpreted within the following limitations:

- Installation validation is not a proof of semantic equivalence or full behavioral preservation.
- LLM generation can vary across model versions, inference configurations, and runs.
- A configured round budget does not guarantee the same number of valid detector evaluations for every package.
- Detector outcomes are specific to the evaluated detector and execution conditions.
- Pending evaluations and external service errors can reduce evaluation coverage.
- Platform compatibility checks are screening mechanisms, not comprehensive proofs of platform support.
- Experimental results should not be generalized beyond the tested packages, configurations, and threat model without additional evidence.

## Responsible Use

Use Pipeline_DySec only for authorized research, defensive evaluation, and security testing of packages you are permitted to analyze.

Run package extraction, installation, and execution in an appropriately isolated environment. Avoid exposing credentials, sensitive files, or unrestricted network access to untrusted packages. Inspect generated code and follow the usage policies of the model and detector services used in the experiment.

## Citation

If you use Pipeline_DySec in academic work, cite the repository and identify the exact commit or release used in your experiments:

```text
TrisNguyen23. Pipeline_DySec.
GitHub repository: https://github.com/TrisNguyen23/Pipeline_DySec
```

Add a formal publication citation here if a paper describing the framework becomes available.

## License

Check the repository for a license before redistributing or reusing this software. If no license is provided, all rights remain with the copyright holder by default.
