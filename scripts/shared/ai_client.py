"""Model-agnostic LLM client using LiteLLM.

This module is OPTIONAL. The MCP tools work without it — they return
structured prompts for your agent's own model to process.

Use this only if you need the skill to call an LLM autonomously for
batch preprocessing tasks (e.g., sentiment analysis on 500 comments
without user intervention).

Supports any OpenAI-compatible endpoint via LLM_BASE_URL:
  - Ollama:    http://localhost:11434
  - LM Studio: http://localhost:1234/v1
  - OpenAI:    https://api.openai.com/v1
  - Any OpenClaw, HuggingFace TGI, vLLM, etc.
"""

from __future__ import annotations

import json
from typing import Any


def is_available() -> bool:
    """Check if LiteLLM and LLM configuration are available."""
    try:
        import litellm  # noqa: F401
        from scripts.shared.config import load_config
        config = load_config()
        return bool(config.get("llm_base_url"))
    except Exception:
        return False


async def complete(
    prompt: str,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> str:
    """
    Send a completion request to the configured LLM.
    Falls back to returning an empty string if not configured.

    Args:
        prompt: The user prompt
        system: Optional system message
        temperature: Sampling temperature (0.0 = deterministic)
        max_tokens: Maximum tokens in response

    Returns:
        Generated text, or empty string if LLM not configured
    """
    if not is_available():
        return ""

    try:
        import litellm
        from scripts.shared.config import load_config

        config = load_config()
        base_url = config.get("llm_base_url", "")
        model = config.get("llm_model", "gpt-3.5-turbo")
        api_key = config.get("llm_api_key") or "ollama"  # Ollama needs any non-empty key

        # LiteLLM model format for custom base URLs
        if base_url and "openai" not in base_url:
            full_model = f"openai/{model}"
        else:
            full_model = model

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await litellm.acompletion(
            model=full_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            api_base=base_url or None,
            api_key=api_key,
        )

        return response.choices[0].message.content or ""

    except Exception as exc:
        # Non-fatal — log and return empty string
        import sys
        print(f"[ai_client] LLM call failed: {exc}", file=sys.stderr)
        return ""


async def analyze_batch(
    items: list[str],
    task: str,
    output_format: str = "json",
) -> list[dict]:
    """
    Run a batch analysis task on a list of text items.
    Useful for: sentiment analysis, language detection, topic classification.

    Args:
        items: List of text strings to analyze
        task: Description of the analysis task
        output_format: Expected output format hint

    Returns:
        List of result dicts, one per item
    """
    if not is_available() or not items:
        return [{"index": i, "result": None} for i in range(len(items))]

    # Process in chunks to avoid token limits
    chunk_size = 20
    results = []

    for i in range(0, len(items), chunk_size):
        chunk = items[i: i + chunk_size]
        numbered = "\n".join(f"{j + 1}. {text}" for j, text in enumerate(chunk))

        prompt = f"""Analyze the following {len(chunk)} items. Task: {task}

Items:
{numbered}

Return a JSON array with {len(chunk)} objects, one per item, each with:
- "index": item number (1-based)
- "result": your analysis result

Return ONLY the JSON array, no other text."""

        response = await complete(prompt, temperature=0.1)
        try:
            chunk_results = json.loads(response)
            results.extend(chunk_results)
        except json.JSONDecodeError:
            results.extend(
                [{"index": i + j + 1, "result": None} for j in range(len(chunk))]
            )

    return results
