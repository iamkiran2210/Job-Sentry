"""
python -m app.ai_features.ai check                         # config + smoke test (run before every deploy)
python -m app.ai_features.ai evaluate [-n 30] [--examples labeled.jsonl]   # how good is the CURRENT model/engine?
python -m app.ai_features.ai optimize [--optimizer bootstrap|mipro] [-n 60] [--examples labeled.jsonl] [--min-gain 0.02]
python -m app.ai_features.ai synthesize -n 50 --out samples.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from .errors import AIError
from .metrics import score_profile
from .models import check_ai_config
from .settings import get_ai_settings
from .synthetic import Sample, dump_jsonl, generate, load_jsonl
from .tasks import RESUME_TASK, build_extractor


def _samples(args) -> list[Sample]:
    return load_jsonl(args.examples) if args.examples else generate(args.n)


async def _evaluate(samples: list[Sample]):
    ex = build_extractor("resume_profile", get_ai_settings())
    scores, lat = [], []
    for s in samples:
        t = time.perf_counter()
        run = await ex.run(s.text)
        lat.append(time.perf_counter() - t)
        scores.append(score_profile(s.gold, run.output, s.text))
    return ex, scores, lat


def cmd_check(_args) -> int:
    st = get_ai_settings()
    print(st)
    try:
        info = check_ai_config(st)
        asyncio.run(_evaluate(generate(1)))
    except AIError as e:
        print(f"FAIL [{e.kind.value}] {e.detail}")
        return 1
    ex = build_extractor("resume_profile", st)
    print(
        f"OK  env={info['env']} engine={info['engine']} models={info['models']} compiled_prompt={ex.artifact.id if ex.artifact else 'none'}"
    )
    if info["offline"]:
        print("NOTE: offline dev model in use; set AI_MODEL to a real model for production.")
    return 0


def cmd_evaluate(args) -> int:
    samples = _samples(args)
    ex, scores, lat = asyncio.run(_evaluate(samples))
    n = len(scores)
    print(
        f"engine={ex.settings.engine} models={ex.model_label} prompt={ex.prompt_version} samples={n}"
    )
    print(f"mean score      {sum(s.total for s in scores) / n:.3f}")
    print(
        f"fabrication     {sum(s.fabricated for s in scores) / n:.1%} of documents had values not found in the text"
    )
    print(f"latency         {sum(lat) / n:.2f}s avg")
    for k in scores[0].fields:
        print(f"  {k:15s} {sum(s.fields[k] for s in scores) / n:.3f}")
    if not args.examples:
        print(
            "NOTE: synthetic data. Use --examples with real labeled resumes before trusting these numbers."
        )
    return 0


def cmd_optimize(args) -> int:
    from .optimize import compile_task  # imports dspy lazily

    st = get_ai_settings()
    if st.offline:
        print(
            "NOTE: AI_MODEL is the offline heuristic: this only checks the optimization plumbing. Use a real model for real gains."
        )
    rep = compile_task(
        RESUME_TASK,
        _samples(args),
        st,
        optimizer=args.optimizer,
        min_gain=args.min_gain,
    )
    print(
        f"baseline={rep.baseline:.3f} optimized={rep.optimized:.3f} train={rep.train} dev={rep.dev}"
    )
    print(
        f"saved -> {rep.path} (id {rep.artifact_id}). Commit it and deploy."
        if rep.saved
        else "not saved: no improvement over baseline."
    )
    return 0


def cmd_synthesize(args) -> int:
    dump_jsonl(generate(args.n, args.seed), args.out)
    print(f"wrote {args.n} synthetic samples to {args.out}")
    return 0


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="python -m app.ai_features.ai",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    for name, fn in (("evaluate", cmd_evaluate), ("optimize", cmd_optimize)):
        s = sub.add_parser(name)
        s.add_argument("-n", type=int, default=30)
        s.add_argument("--examples")
        if name == "optimize":
            s.add_argument("--optimizer", choices=["bootstrap", "mipro"], default="bootstrap")
            s.add_argument("--min-gain", type=float, default=0.0)
        s.set_defaults(fn=fn)
    s = sub.add_parser("synthesize")
    s.add_argument("-n", type=int, default=50)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_synthesize)
    args = p.parse_args(argv)
    sys.exit(args.fn(args))
