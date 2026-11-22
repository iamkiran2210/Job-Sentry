"""Optional, zero-overhead LangSmith tracing emitter for Job Sentry AI tasks.

Enabled only when BOTH `LANGSMITH_TRACING=true` (or `LANGCHAIN_TRACING_V2=true`) and
`LANGSMITH_API_KEY` (or `LANGCHAIN_API_KEY`) are configured. When unconfigured, all calls
are immediate no-ops with zero latency or dependency overhead.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("ai.tracing")

_DEFAULT_ENDPOINT = "https://api.smith.langchain.com"


def is_langsmith_enabled() -> bool:
    flag = (
            os.getenv("LANGSMITH_TRACING")
            or os.getenv("LANGCHAIN_TRACING_V2")
            or ""
    ).strip().lower()
    api_key = (
            os.getenv("LANGSMITH_API_KEY")
            or os.getenv("LANGCHAIN_API_KEY")
            or ""
    ).strip()
    return flag in {"1", "true", "yes", "on"} and bool(api_key)


def langsmith_status() -> dict[str, Any]:
    return {
        "enabled": is_langsmith_enabled(),
        "project": (
                os.getenv("LANGSMITH_PROJECT")
                or os.getenv("LANGCHAIN_PROJECT")
                or "job-sentry"
        ),
        "endpoint": (
                os.getenv("LANGSMITH_ENDPOINT")
                or os.getenv("LANGCHAIN_ENDPOINT")
                or _DEFAULT_ENDPOINT
        ),
    }


async def _post_run(payload: dict[str, Any], endpoint: str, api_key: str) -> None:
    try:
        import httpx

        url = endpoint.rstrip("/") + "/runs"
        async with httpx.AsyncClient(timeout=4.0) as client:
            await client.post(
                url,
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("LangSmith trace post skipped (%s)", type(exc).__name__)


def emit_langsmith_trace(
        *,
        task_name: str,
        tier: str,
        engine: str,
        model: str,
        prompt_version: str,
        cached: bool,
        start_time: datetime,
        end_time: datetime,
        input_chars: int,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error: str | None = None,
        output_summary: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget LangSmith run trace (never stores raw PII/resume text)."""
    if not is_langsmith_enabled():
        return
    api_key = (
            os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY") or ""
    ).strip()
    if not api_key:
        return
    endpoint = (
            os.getenv("LANGSMITH_ENDPOINT")
            or os.getenv("LANGCHAIN_ENDPOINT")
            or _DEFAULT_ENDPOINT
    ).strip()
    project = (
            os.getenv("LANGSMITH_PROJECT")
            or os.getenv("LANGCHAIN_PROJECT")
            or "job-sentry"
    ).strip()

    payload: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": f"jobsentry.{task_name}",
        "run_type": "chain",
        "session_name": project,
        "start_time": start_time.astimezone(timezone.utc).isoformat(),
        "end_time": end_time.astimezone(timezone.utc).isoformat(),
        "inputs": {
            "task": task_name,
            "tier": tier,
            "engine": engine,
            "model": model,
            "prompt_version": prompt_version,
            "input_chars": input_chars,
        },
        "outputs": output_summary or {"status": "error" if error else "ok"},
        "error": error,
        "extra": {
            "metadata": {
                "tier": tier,
                "engine": engine,
                "model": model,
                "prompt_version": prompt_version,
                "cached": cached,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        },
        "tags": ["job-sentry", task_name, f"tier:{tier}", f"engine:{engine}"],
    }

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_post_run(payload, endpoint, api_key))
    except RuntimeError:
        pass
