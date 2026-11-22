"""DSPy side: typed Signature/Predict program, LM wiring, and the runtime runner. Imported lazily."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import dspy

from .artifacts import Artifact
from .engine import SAFETY_RULES, TaskSpec, ensure_safety
from .settings import AISettings

_PREFIX_MAP = {
    # Pydantic AI calls Google's Gemini API provider "google"; LiteLLM calls it "gemini".
    "google": "gemini",
    "google-gla": "gemini",
    "google-vertex": "vertex_ai",
    "ollama": "ollama_chat",
    "bedrock": "bedrock",
    "groq": "groq",
    "mistral": "mistral",
}
_OPENAI_REASONING_MODEL = re.compile(
    r"^(?:o[1345](?:-(?:mini|nano|pro))?(?:-\d{4}-\d{2}-\d{2})?|"
    r"gpt-5(?:\.\d+)*(?!-chat)(?:-.*)?)$",
    re.IGNORECASE,
)
_OPENAI_REASONING_MIN_TOKENS = 16_000


def to_litellm_name(model_id: str) -> str:
    """Pydantic AI 'provider:model' -> LiteLLM 'provider/model'."""
    if "/" in model_id and ":" not in model_id:
        return model_id
    provider, _, name = model_id.partition(":")
    return f"{_PREFIX_MAP.get(provider, provider)}/{name}"


def build_program(
        spec: TaskSpec[Any],
        instructions: str | None = None,
        *,
        force_predict: bool = False,
) -> dspy.Module:
    """document (str) -> output (typed Pydantic model). Field names are part of the artifact contract."""
    sig = dspy.make_signature(
        {
            "document": (str, dspy.InputField()),
            "output": (spec.output_type, dspy.OutputField()),
        },
        instructions=ensure_safety(
            instructions or spec.instructions, task_kind=spec.task_kind
        ),
    )
    if getattr(spec, "use_chain_of_thought", False) and not force_predict:
        return dspy.ChainOfThought(sig)
    return dspy.Predict(sig)


def _heuristic_response(task: str, request):
    """Build a canonical DSPy response from the deterministic offline extractor."""
    import json
    import re

    from dspy.lm15 import Message, Response, Usage

    from .heuristic import _TASKS

    content = next(
        (
            message.text
            for message in reversed(request.messages)
            if message.role in {"user", "developer"} and message.text is not None
        ),
        "",
    )
    match = re.search(r"<document>\n?(.*?)\n?</document>", content, re.S)
    data = _TASKS[task](match.group(1) if match else content)
    output = f"[[ ## output ## ]]\n{json.dumps(data)}\n\n[[ ## completed ## ]]"
    return Response(
        id=None,
        model=request.model,
        message=Message.assistant(output),
        finish_reason="stop",
        usage=Usage(
            input_tokens=len(content) // 4,
            output_tokens=len(output) // 4,
        ),
    )


class HeuristicEngine:
    """Synchronous normalized engine for offline DSPy evaluation and optimization."""

    def __init__(self, task: str) -> None:
        self.task = task

    def complete(self, request):
        return _heuristic_response(self.task, request)


class AsyncHeuristicEngine:
    """Async counterpart used by the DSPy runtime's ``Predict.acall`` path."""

    def __init__(self, task: str) -> None:
        self.task = task

    async def complete(self, request):
        return _heuristic_response(self.task, request)


def build_heuristic_lm(task: str) -> dspy.LM:
    """Create the offline LM without DSPy's deprecated BaseLM.forward interface."""
    return dspy.LM(
        model=f"heuristic/{task}",
        model_type="chat",
        temperature=0.0,
        max_tokens=8192,
        cache=False,
        engine=HeuristicEngine(task),
        async_engine=AsyncHeuristicEngine(task),
    )


def build_lm(
        settings: AISettings,
        task: str,
        model: str | None = None,
        *,
        timeout_cap: float | None = None,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
) -> dspy.LM:
    first = model or settings.model_chain[0]
    if first == "heuristic":
        return build_heuristic_lm(task)
    name = settings.dspy_lm or to_litellm_name(first)
    eff_timeout = (
        min(float(settings.timeout_seconds), float(timeout_cap))
        if timeout_cap is not None
        else float(settings.timeout_seconds)
    )
    effective_max = (
        min(settings.max_tokens, int(max_output_tokens))
        if max_output_tokens is not None
        else settings.max_tokens
    )
    kwargs: dict[str, Any] = {
        "max_tokens": effective_max,
        "timeout": eff_timeout,
        "num_retries": 0,
        "cache": False,
    }
    provider = name.partition("/")[0]
    model_name = name.rpartition("/")[2]
    is_openai_reasoning = (
            provider == "openai" and _OPENAI_REASONING_MODEL.fullmatch(model_name) is not None
    )
    if is_openai_reasoning:
        # DSPy routes these through max_completion_tokens and requires at least
        # 16k (or None). Bound reasoning effort to keep latency & hidden reasoning tokens low.
        kwargs["max_tokens"] = max(effective_max, _OPENAI_REASONING_MIN_TOKENS)
        if reasoning_effort and reasoning_effort != "none":
            kwargs["reasoning_effort"] = reasoning_effort
    api_key = None
    if provider in {"gemini", "google"} and settings.google_api_key is not None:
        api_key = settings.google_api_key.get_secret_value()
    elif provider == "openai" and settings.openai_api_key is not None:
        api_key = settings.openai_api_key.get_secret_value()
    elif provider == "anthropic" and settings.anthropic_api_key is not None:
        api_key = settings.anthropic_api_key.get_secret_value()
    if api_key is not None:
        kwargs["api_key"] = api_key
    if settings.temperature is not None and not is_openai_reasoning:
        kwargs["temperature"] = settings.temperature
    elif not is_openai_reasoning:
        kwargs["temperature"] = 0.0
    return dspy.LM(name, **kwargs)


def _is_native_reasoning_lm(lm: dspy.LM) -> bool:
    model_id = str(getattr(lm, "model", "") or "")
    provider, _, model_name = model_id.partition("/")
    return provider == "openai" and _OPENAI_REASONING_MODEL.fullmatch(model_name) is not None


class DSPyRunner:
    def __init__(
            self, spec: TaskSpec[Any], settings: AISettings, artifact: Artifact | None
    ) -> None:
        self.spec, self.settings = spec, settings
        self.program = build_program(spec)
        # Lightweight Predict program used on native reasoning models (e.g. gpt-5.4-mini/nano)
        # to avoid paying double-reasoning tokens (native internal reasoning + verbose CoT field).
        self.fast_program = (
            build_program(spec, force_predict=True)
            if getattr(spec, "use_chain_of_thought", False)
            else self.program
        )
        if artifact is not None:
            self.program.load(str(artifact.path))
            # compiled instructions may have been rewritten by the optimizer: re-assert the safety rules
            predictor = getattr(self.program, "predict", self.program)
            predictor.signature = predictor.signature.with_instructions(
                ensure_safety(predictor.signature.instructions, task_kind=spec.task_kind)
            )
            self.fast_program = self.program
        chain = settings.model_chain_for_tier(spec.tier)
        effort = (
            settings.reasoning_effort_reasoning
            if spec.task_kind == "reasoning"
            else settings.reasoning_effort_extraction
        )
        # An explicit DSPy LM is an intentional override. Otherwise keep the tier-optimized
        # primary/fallback chain, capping per-LM timeout when fallbacks exist for rapid failover.
        self._per_lm_timeout = (
            min(float(settings.timeout_seconds), 25.0)
            if len(chain) > 1 and not settings.dspy_lm
            else min(float(settings.timeout_seconds), 45.0)
        )
        self.lms = (
            [
                build_lm(
                    settings,
                    spec.name,
                    timeout_cap=self._per_lm_timeout,
                    max_output_tokens=spec.max_output_tokens,
                    reasoning_effort=effort,
                )
            ]
            if settings.dspy_lm
            else [
                build_lm(
                    settings,
                    spec.name,
                    model,
                    timeout_cap=self._per_lm_timeout,
                    max_output_tokens=spec.max_output_tokens,
                    reasoning_effort=effort,
                )
                for model in chain
            ]
        )

    async def run(self, wrapped_document: str):
        # DSPy's async Predict path currently stalls with its custom async engine
        # under the offline heuristic LM. Run the deterministic local adapter via
        # the synchronous engine in a worker thread; real providers stay async.
        if self.settings.model_chain[0] == "heuristic":
            # The offline heuristic is itself the deterministic DSPy development
            # adapter. Bypass Predict's LM protocol (which stalls in DSPy 3.x for
            # custom engines) while preserving the typed output contract.
            import re
            from .heuristic import _TASKS

            match = re.search(r"<document>\n?(.*?)\n?</document>", wrapped_document, re.S)
            text = match.group(1) if match else wrapped_document
            raw = _TASKS[self.spec.name](text)
            parsed = self.spec.output_type.model_validate(raw)
            return parsed, max(1, len(text) // 4), max(1, len(str(raw)) // 4)
        last_error = None
        for lm in self.lms:
            try:
                active_program = (
                    self.fast_program if _is_native_reasoning_lm(lm) else self.program
                )

                # Run synchronously inside a worker thread with JSONAdapter to avoid
                # DSPy 3.x lm15 async keep-alive stalls (_read_head hangs on reused sockets)
                # and to enforce native structured JSON output on Pydantic models.
                def _invoke(active_lm: dspy.LM, prog: dspy.Module):
                    with dspy.context(lm=active_lm, adapter=dspy.JSONAdapter()):
                        return prog(document=wrapped_document)

                pred = await asyncio.wait_for(
                    asyncio.to_thread(_invoke, lm, active_program),
                    timeout=self._per_lm_timeout,
                )
                out = pred.output
                if not isinstance(out, self.spec.output_type):
                    out = self.spec.output_type.model_validate(out)
                usage = None
                try:
                    usage = (lm.history[-1] or {}).get("usage") or {}
                except Exception:  # noqa: BLE001
                    usage = {}
                return (
                    out,
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("DSPy has no configured language models")
