import requests

from config.settings import (
    OLLAMA_API,
    MODEL_NAME,
    TEMPERATURE,
    LLM_TIMEOUT,
)


def generate_variant(prompt):

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": TEMPERATURE
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

        generated_code = result.get(
            "response",
            ""
        ).strip()

        generated_code = (
            generated_code
            .replace("```python", "")
            .replace("```", "")
            .strip()
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

    except Exception as exc:

        return {
            "success": False,
            "code": None,
            "error": str(exc),
        }