from __future__ import annotations

import re
import time
from typing import Any

import requests

from config.settings import (
    LLM_TIMEOUT,
    MODEL_NAME,
    OLLAMA_API,
    TEMPERATURE,
)


def _clean_code(text: str) -> str:

    text = text.strip()

    python_match = re.search(
        r"```python\s*(.*?)```",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if python_match:
        return python_match.group(1).strip()

    generic_match = re.search(
        r"```\s*(.*?)```",
        text,
        flags=re.DOTALL,
    )

    if generic_match:
        return generic_match.group(1).strip()

    return text


def _validate_python(
    code: str,
) -> None:

    compile(
        code,
        "<generated_variant>",
        "exec",
    )


def generate_variant(
    prompt: str,
) -> dict[str, Any]:

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": TEMPERATURE,
        },
    }

    start = time.monotonic()

    try:

        response = requests.post(
            OLLAMA_API,
            json=payload,
            timeout=LLM_TIMEOUT,
        )

        response.raise_for_status()

        elapsed = (
            time.monotonic() - start
        )

        data = response.json()

        raw_response = data.get(
            "response",
            "",
        )

        code = _clean_code(
            raw_response
        )

        if not code:
            return {
                "success": False,
                "code": None,
                "tokens": {},
                "response_metadata": data,
                "model": MODEL_NAME,
                "temperature": TEMPERATURE,
                "error": (
                    "Ollama returned empty code."
                ),
            }

        try:
            _validate_python(code)

        except SyntaxError as exc:

            return {
                "success": False,
                "code": code,
                "tokens": {},
                "response_metadata": data,
                "model": MODEL_NAME,
                "temperature": TEMPERATURE,
                "error": (
                    "Generated code has invalid "
                    f"Python syntax: {exc}"
                ),
            }

        metadata = {
            "model": MODEL_NAME,
            "api": OLLAMA_API,
            "temperature": TEMPERATURE,
            "elapsed_seconds": elapsed,
            "created_at": data.get(
                "created_at"
            ),
            "done": data.get(
                "done"
            ),
            "done_reason": data.get(
                "done_reason"
            ),
            "total_duration": data.get(
                "total_duration"
            ),
            "load_duration": data.get(
                "load_duration"
            ),
            "prompt_eval_count": data.get(
                "prompt_eval_count"
            ),
            "prompt_eval_duration": data.get(
                "prompt_eval_duration"
            ),
            "eval_count": data.get(
                "eval_count"
            ),
            "eval_duration": data.get(
                "eval_duration"
            ),
        }

        tokens = {
            "prompt_eval_count": data.get(
                "prompt_eval_count"
            ),
            "eval_count": data.get(
                "eval_count"
            ),
        }

        return {
            "success": True,
            "code": code,
            "tokens": tokens,
            "response_metadata": metadata,
            "model": MODEL_NAME,
            "temperature": TEMPERATURE,
            "error": None,
        }

    except requests.Timeout:

        return {
            "success": False,
            "code": None,
            "tokens": {},
            "response_metadata": {},
            "model": MODEL_NAME,
            "temperature": TEMPERATURE,
            "error": (
                f"Ollama request timed out "
                f"after {LLM_TIMEOUT}s."
            ),
        }

    except requests.RequestException as exc:

        return {
            "success": False,
            "code": None,
            "tokens": {},
            "response_metadata": {},
            "model": MODEL_NAME,
            "temperature": TEMPERATURE,
            "error": (
                f"Ollama request failed: {exc}"
            ),
        }

    except Exception as exc:

        return {
            "success": False,
            "code": None,
            "tokens": {},
            "response_metadata": {},
            "model": MODEL_NAME,
            "temperature": TEMPERATURE,
            "error": (
                f"Generation failed: {exc}"
            ),
        }