from __future__ import annotations

import requests

from config.settings import (
    OLLAMA_API,
    MODEL_NAME,
    TEMPERATURE,
    LLM_TIMEOUT,
)


def _clean_generated_code(response_text: str) -> str:
    """
    Remove markdown code fences accidentally returned by the LLM.
    """

    code = response_text.strip()

    if code.startswith("```python"):
        code = code[len("```python"):].strip()

    elif code.startswith("```"):
        code = code[len("```"):].strip()

    if code.endswith("```"):
        code = code[:-3].strip()

    return code


def generate_variant(prompt: str) -> dict:
    """
    Generate one source-code variant using the configured Ollama model.
    """

    if not prompt or not prompt.strip():
        return {
            "success": False,
            "code": None,
            "error": "Prompt is empty.",
        }

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": TEMPERATURE,
        },
    }

    try:
        response = requests.post(
            OLLAMA_API,
            json=payload,
            timeout=LLM_TIMEOUT,
        )

        response.raise_for_status()

        result = response.json()

        if not isinstance(result, dict):
            raise RuntimeError(
                "Ollama returned a non-object JSON response."
            )

        response_text = result.get(
            "response"
        )

        if not isinstance(response_text, str):
            raise RuntimeError(
                "Ollama response does not contain "
                "a valid 'response' string."
            )

        generated_code = _clean_generated_code(
            response_text
        )

        if not generated_code:
            raise RuntimeError(
                "LLM returned empty code."
            )

        return {
            "success": True,
            "code": generated_code,
            "error": None,
        }

    except requests.RequestException as exc:

        return {
            "success": False,
            "code": None,
            "error": (
                f"Ollama request failed: {exc}"
            ),
        }

    except ValueError as exc:

        return {
            "success": False,
            "code": None,
            "error": (
                f"Invalid Ollama JSON response: {exc}"
            ),
        }

    except Exception as exc:

        return {
            "success": False,
            "code": None,
            "error": str(exc),
        }