from __future__ import annotations

import os
import re
import time
from typing import Any, Callable
import requests

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.getenv("LLM_MODEL_NAME", "huihui_ai/qwen3-abliterated:14b-v2")
THINKING_MODE = os.getenv("QWEN_THINKING_MODE", "false").casefold() in {"1", "true", "yes"}
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))

THINK_BLOCK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)
CODE_FENCE_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _separate_thinking_and_code(raw_text: str) -> tuple[str, str]:
    """
    Separate Qwen3 <think>...</think> reasoning traces from the final Python code snippet
    so that AST validation gates only receive clean Python syntax.
    """
    if not raw_text:
        return "", ""

    thinking_parts: list[str] = []
    for match in THINK_BLOCK_RE.finditer(raw_text):
        thinking_parts.append(match.group(1).strip())

    cleaned = THINK_BLOCK_RE.sub("", raw_text)
    if "<think>" in cleaned:
        cleaned = cleaned.split("<think>", 1)[0]
    cleaned = cleaned.strip()

    fence_match = CODE_FENCE_RE.search(cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    return "\n\n".join(thinking_parts), cleaned


def generate_variant(
    prompt: str,
    stream_callback: Callable[[str], None] | None = None,
    thinking_override: bool | None = None,
) -> dict[str, Any]:
    """
    Query Qwen3 via Ollama with explicit control over thinking vs. non-thinking mode,
    returning clean target code and detailed token/latency telemetry for RQ2 & RQ4.
    """
    use_thinking = THINKING_MODE if thinking_override is None else thinking_override

    mode_directive = "/think" if use_thinking else "/no_think"
    effective_prompt = f"{prompt.rstrip()}\n\n{mode_directive}\n"

    payload: dict[str, Any] = {
        "model": MODEL_NAME,
        "prompt": effective_prompt,
        "stream": stream_callback is not None,
        "options": {
            "temperature": TEMPERATURE,
            "num_predict": 2048 if use_thinking else 1024,
        },
    }

    t_start = time.monotonic()
    raw_chunks: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0

    try:
        if stream_callback is not None:
            with requests.post(OLLAMA_API_URL, json=payload, stream=True, timeout=180) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    import json
                    chunk_data = json.loads(line)
                    piece = chunk_data.get("response", "")
                    if piece:
                        raw_chunks.append(piece)
                        stream_callback(piece)
                    if chunk_data.get("done"):
                        prompt_tokens = int(chunk_data.get("prompt_eval_count") or 0)
                        completion_tokens = int(chunk_data.get("eval_count") or 0)
        else:
            resp = requests.post(OLLAMA_API_URL, json=payload, timeout=180)
            resp.raise_for_status()
            data = resp.json()
            raw_chunks.append(data.get("response", ""))
            prompt_tokens = int(data.get("prompt_eval_count") or 0)
            completion_tokens = int(data.get("eval_count") or 0)

    except Exception as exc:
        latency = time.monotonic() - t_start
        return {
            "success": False,
            "code": "",
            "error": str(exc),
            "latency_seconds": latency,
            "tokens": None,
        }

    latency = time.monotonic() - t_start
    raw_output = "".join(raw_chunks)
    thinking_trace, clean_code = _separate_thinking_and_code(raw_output)

    thinking_char_ratio = (
        len(thinking_trace) / max(len(raw_output), 1) if thinking_trace else 0.0
    )
    estimated_reasoning_tokens = int(round(completion_tokens * thinking_char_ratio))
    estimated_code_tokens = max(0, completion_tokens - estimated_reasoning_tokens)

    return {
        "success": bool(clean_code.strip()),
        "code": clean_code,
        "raw_output": raw_output,
        "thinking_trace": thinking_trace,
        "thinking_mode": use_thinking,
        "latency_seconds": latency,
        "tokens": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": estimated_reasoning_tokens,
            "code_tokens": estimated_code_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "latency_seconds": latency,
            "thinking_mode": use_thinking,
        },
    }