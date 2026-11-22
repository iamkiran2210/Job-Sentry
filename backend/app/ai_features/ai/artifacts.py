"""
Compiled (DSPy-optimized) prompt artifacts.

`python -m app.ai_features.ai optimize` writes  compiled/<task>.json  (DSPy's own saved-program JSON + a `job_sentry`
metadata block). At runtime BOTH engines read it as plain JSON, so production does not need DSPy installed to
benefit from optimization. An artifact is ignored (with a warning) if the task's output schema or default
instructions changed since it was compiled, so a stale prompt can never silently pair with a new schema.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .settings import AISettings

log = logging.getLogger("ai.artifacts")


@dataclass
class Artifact:
    task: str
    path: Path
    instructions: str | None
    demos: list[dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return str(self.meta.get("id") or "unknown")


def fingerprint(output_schema: dict[str, Any], base_instructions: str) -> str:
    blob = json.dumps({"schema": output_schema, "instructions": base_instructions}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def artifact_path(settings: AISettings, task: str) -> Path:
    return Path(settings.compiled_dir) / f"{task}.json"


def load_artifact(settings: AISettings, task: str, expected_fingerprint: str) -> Artifact | None:
    if not settings.use_compiled:
        return None
    path = artifact_path(settings, task)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        log.warning("compiled artifact %s is unreadable; ignoring", path.name)
        return None
    meta = raw.get("job_sentry") or {}
    if meta.get("fingerprint") != expected_fingerprint:
        log.warning(
            "compiled artifact %s is stale (schema/instructions changed); ignoring. Re-run `python -m app.ai_features.ai optimize`.",
            path.name,
        )
        return None
    # DSPy saves a Predict as {"demos": [...], "signature": {"instructions": ...}, ...}
    pred = raw.get("predict") if isinstance(raw.get("predict"), dict) else raw
    return Artifact(
        task=task,
        path=path,
        instructions=(pred.get("signature") or {}).get("instructions"),
        demos=[d for d in (pred.get("demos") or []) if isinstance(d, dict)],
        meta=meta,
    )


def stamp_artifact(path: Path, **meta: Any) -> str:
    """Add the job_sentry metadata block (incl. a content id) to a freshly saved DSPy program JSON."""
    raw = json.loads(path.read_text())
    raw.pop("job_sentry", None)
    art_id = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()[:10]
    raw["job_sentry"] = {**meta, "id": art_id}
    path.write_text(json.dumps(raw, indent=2, sort_keys=True))
    return art_id


def render_demos(demos: list[dict[str, Any]], *, limit: int = 3, max_chars: int = 6000) -> str:
    """Few-shot examples as prompt text (input document + expected structured output)."""
    blocks: list[str] = []
    for d in demos[:limit]:
        doc = d.get("document")
        out = d.get("output")
        if doc is None or out is None:
            continue
        out_s = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        block = f"<example>\n<document>\n{str(doc)[: max_chars // 2]}\n</document>\nExpected output:\n{out_s[: max_chars // 2]}\n</example>"
        blocks.append(block)
    return (
        (
                "\n\nWorked examples (format reference only; never copy their values):\n"
                + "\n".join(blocks)
        )
        if blocks
        else ""
    )
