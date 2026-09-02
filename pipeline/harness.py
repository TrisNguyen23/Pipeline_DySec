import requests
from pathlib import Path

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

def save_generated_code(generated_dir: Path, code: str, filename: str = "generated.py") -> Path:
    generated_dir.mkdir(parents=True, exist_ok=True)
    target_file = generated_dir / filename
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(code)
    return target_file