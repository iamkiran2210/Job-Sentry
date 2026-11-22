"""
DSPy optimization + evaluation for the resume task.

    baseline  = score of the un-optimized DSPy program on a held-out dev split
    optimized = score after BootstrapFewShot / MIPROv2
    -> the artifact is written ONLY if optimized >= baseline + min_gain, so a worse prompt never ships.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

import dspy

from app.ai_features.schemas.resume_extraction import ExtractedProfileData

from .artifacts import artifact_path, stamp_artifact
from .dspy_engine import build_lm, build_program
from .engine import TaskSpec, wrap_document
from .metrics import score_profile
from .settings import AISettings
from .synthetic import Sample

log = logging.getLogger("ai.optimize")


def _as_profile(out: Any) -> ExtractedProfileData:
    return (
        out
        if isinstance(out, ExtractedProfileData)
        else ExtractedProfileData.model_validate(out or {})
    )


def make_metric(threshold: float | None = None):
    def metric(example, pred, trace=None):
        try:
            s = score_profile(example.gold, _as_profile(pred.output), example.text).total
        except Exception:  # noqa: BLE001  (unparseable prediction scores zero)
            s = 0.0
        return (s >= threshold) if (trace is not None and threshold is not None) else s

    return metric


def to_examples(samples: list[Sample]) -> list[dspy.Example]:
    return [
        dspy.Example(document=wrap_document(s.text), text=s.text, gold=s.gold).with_inputs(
            "document"
        )
        for s in samples
    ]


def _pct(result: Any) -> float:
    score = float(getattr(result, "score", result))
    return score / 100 if score > 1.0 else score


@dataclass
class CompileReport:
    baseline: float
    optimized: float
    saved: bool
    path: str | None
    artifact_id: str | None
    optimizer: str
    train: int
    dev: int


def compile_task(
        spec: TaskSpec[Any],
        samples: list[Sample],
        settings: AISettings,
        *,
        optimizer: str = "bootstrap",
        min_gain: float = 0.0,
        dev_fraction: float = 0.3,
        threads: int = 4,
        lm: Any = None,
) -> CompileReport:
    if len(samples) < 6:
        raise ValueError("need at least 6 labeled samples (more is better; aim for 30+ real ones)")
    examples = to_examples(samples)
    k = max(2, int(len(examples) * dev_fraction))
    dev, train = examples[:k], examples[k:]
    lm = lm or build_lm(settings, spec.name)
    metric = make_metric()
    evaluate = dspy.Evaluate(devset=dev, metric=metric, num_threads=threads, display_progress=False)

    with dspy.context(lm=lm):
        student = build_program(spec)
        baseline = _pct(evaluate(student))
        if optimizer == "bootstrap":
            opt = dspy.BootstrapFewShot(
                metric=make_metric(0.8), max_bootstrapped_demos=3, max_labeled_demos=3
            )
            compiled = opt.compile(student, trainset=train)
        elif optimizer == "mipro":
            opt = dspy.MIPROv2(metric=metric, auto="light", num_threads=threads)
            compiled = opt.compile(student, trainset=train, requires_permission_to_run=False)
        else:
            raise ValueError("optimizer must be 'bootstrap' or 'mipro'")
        optimized = _pct(evaluate(compiled))

    saved, path, art_id = False, artifact_path(settings, spec.name), None
    if optimized >= baseline + min_gain:
        path.parent.mkdir(parents=True, exist_ok=True)
        compiled.save(str(path))
        art_id = stamp_artifact(
            path,
            task=spec.name,
            fingerprint=spec.fingerprint,
            optimizer=optimizer,
            baseline_score=round(baseline, 4),
            optimized_score=round(optimized, 4),
            train_size=len(train),
            dev_size=len(dev),
            model=settings.dspy_lm or settings.model_chain[0],
            dspy_version=dspy.__version__,
            created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            spec_version=spec.version,
        )
        saved = True
    return CompileReport(
        baseline,
        optimized,
        saved,
        str(path) if saved else None,
        art_id,
        optimizer,
        len(train),
        len(dev),
    )
