from __future__ import annotations

import requests

from config.settings import (
    OLLAMA_API,
    MODEL_NAME,
    TEMPERATURE,
    LLM_TIMEOUT,
)


def _clean_code(
    response_text: str,
) -> str:

    code = response_text.strip()

    if code.startswith("```python"):
        code = code[len("```python"):].strip()

    elif code.startswith("```"):
        code = code[len("```"):].strip()

    if code.endswith("```"):
        code = code[:-3].strip()

    return code


def generate_variant(
    prompt: str,
) -> dict:

    if not prompt.strip():
        return {
            "success": False,
            "code": None,
            "tokens": {},
            "response_metadata": {},
            "error": "Prompt is empty.",
        }

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "temperature": TEMPERATURE,
        "stream": False,
    }

    try:

        response = requests.post(
            OLLAMA_API,
            json=payload,
            timeout=LLM_TIMEOUT,
        )

        response.raise_for_status()

        result = response.json()

        response_text = result.get("response")

        if not isinstance(response_text, str):
            raise RuntimeError(
                "Invalid Ollama response: "
                "missing response text."
            )

        code = _clean_code(
            response_text
        )

        if not code:
            raise RuntimeError(
                "LLM returned empty code."
            )

        tokens = {
            key: result[key]
            for key in (
                "prompt_eval_count",
                "eval_count",
                "prompt_eval_duration",
                "eval_duration",
                "total_duration",
                "load_duration",
            )
            if key in result
        }

        return {
            "success": True,
            "code": code,
            "tokens": tokens,
            "response_metadata": {
                key: value
                for key, value in result.items()
                if key != "response"
            },
            "error": None,
        }

    except requests.RequestException as exc:

        return {
            "success": False,
            "code": None,
            "tokens": {},
            "response_metadata": {},
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
            "error": str(exc),
        }