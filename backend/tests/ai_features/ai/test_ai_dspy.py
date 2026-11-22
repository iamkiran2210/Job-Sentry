"""DSPy side: runtime engine, compiled artifacts shared with Pydantic AI, optimizer, CLI."""

import json
from types import SimpleNamespace

import pytest

from app.ai_features.ai import artifacts
from app.ai_features.ai.engine import SAFETY_RULES, StructuredExtractor
from app.ai_features.ai.errors import AIError
from app.ai_features.ai.settings import AISettings
from app.ai_features.ai.synthetic import generate
from app.ai_features.ai.tasks import RESUME_TASK, build_extractor

dspy = pytest.importorskip("dspy")


def S(tmp_path, **kw):
    return AISettings(_env_file=None, compiled_dir=tmp_path, **kw)


@pytest.mark.asyncio
async def test_dspy_engine_returns_typed_validated_output_offline(tmp_path):
    ex = build_extractor("resume_profile", S(tmp_path, engine="dspy"))
    sm = generate(1)[0]
    run = await ex.run(sm.text)
    assert run.engine == "dspy" and type(run.output).__name__ == "ExtractedProfileData"
    assert (
            run.output.contact.email.value == sm.gold["email"]
            and run.input_tokens
            and run.output_tokens
    )


@pytest.mark.asyncio
async def test_dspy_with_testmodel_is_a_clear_config_error(tmp_path):
    with pytest.raises(AIError) as e:
        await build_extractor("resume_profile", S(tmp_path, engine="dspy", model="test")).run("x")
    assert e.value.kind.value == "not_configured"


def test_litellm_name_mapping():
    from app.ai_features.ai.dspy_engine import to_litellm_name

    assert to_litellm_name("anthropic:claude-sonnet-5-5") == "anthropic/claude-sonnet-5-5"
    assert to_litellm_name("google-gla:gemini-2.5-pro") == "gemini/gemini-2.5-pro"
    assert to_litellm_name("ollama:llama3.2") == "ollama_chat/llama3.2"
    assert to_litellm_name("openai/gpt-5") == "openai/gpt-5"


def write_artifact(
        tmp_path, *, instructions="Be precise and concise.", fingerprint=None, demos=None
):
    from app.ai_features.ai.dspy_engine import build_program

    prog = build_program(RESUME_TASK, instructions)
    path = artifacts.artifact_path(S(tmp_path), "resume_profile")
    prog.save(str(path))
    raw = json.loads(path.read_text())
    raw["demos"] = (
        demos
        if demos is not None
        else [
            {
                "document": "<document>\nJane\n</document>",
                "output": {"full_name": {"value": "Jane"}},
            }
        ]
    )
    raw["signature"]["instructions"] = (
        instructions  # as an optimizer that dropped our safety text would leave it
    )
    path.write_text(json.dumps(raw))
    return artifacts.stamp_artifact(
        path,
        task="resume_profile",
        fingerprint=fingerprint or RESUME_TASK.fingerprint,
        optimizer="test",
    )


def test_compiled_artifact_is_used_with_safety_rules_forced_back_in(tmp_path):
    art_id = write_artifact(tmp_path)
    ex = StructuredExtractor(RESUME_TASK, S(tmp_path))
    ins = ex.instructions()
    assert ex.artifact is not None and ex.prompt_version == f"{RESUME_TASK.version}+{art_id}"
    assert "Be precise and concise." in ins and "Worked examples" in ins
    assert ins.startswith(SAFETY_RULES)  # the optimizer never gets to remove the safety rules


def test_stale_or_disabled_or_corrupt_artifact_is_ignored(tmp_path):
    write_artifact(tmp_path, fingerprint="deadbeef")
    assert (
            StructuredExtractor(RESUME_TASK, S(tmp_path)).artifact is None
    )  # schema/instructions changed since compile
    write_artifact(tmp_path)
    assert StructuredExtractor(RESUME_TASK, S(tmp_path, use_compiled=False)).artifact is None
    artifacts.artifact_path(S(tmp_path), "resume_profile").write_text("{not json")
    assert StructuredExtractor(RESUME_TASK, S(tmp_path)).artifact is None


@pytest.mark.asyncio
async def test_compiled_artifact_works_in_both_engines(tmp_path):
    write_artifact(tmp_path)
    sm = generate(1)[0]
    for engine in ("pydantic_ai", "dspy"):
        run = await build_extractor("resume_profile", S(tmp_path, engine=engine)).run(sm.text)
        assert (
                run.compiled
                and run.prompt_version.startswith(RESUME_TASK.version + "+")
                and run.output.full_name.value == sm.gold["full_name"]
        )


def test_runtime_does_not_need_dspy_to_use_a_compiled_artifact(tmp_path):
    """Prod image can omit DSPy: artifacts are plain JSON read by artifacts.py (no dspy import there)."""
    import subprocess, sys, textwrap

    write_artifact(tmp_path)
    code = textwrap.dedent(f"""
        import sys, importlib.abc
        class Block(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name == "dspy" or name.startswith("dspy."): raise ImportError("dspy blocked")
        sys.meta_path.insert(0, Block())
        from app.ai_features.ai.settings import AISettings
        from app.ai_features.ai.engine import StructuredExtractor
        from app.ai_features.ai.tasks import RESUME_TASK
        ex = StructuredExtractor(RESUME_TASK, AISettings(_env_file=None, compiled_dir={str(tmp_path)!r}))
        assert ex.artifact is not None and "Worked examples" in ex.instructions()
        print("ok")
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=".")
    assert out.stdout.strip() == "ok", out.stderr[-500:]


def test_optimizer_saves_only_when_not_worse_and_records_scores(tmp_path):
    from app.ai_features.ai.dspy_engine import build_heuristic_lm
    from app.ai_features.ai.optimize import compile_task

    st = S(tmp_path, engine="dspy")
    rep = compile_task(
        RESUME_TASK,
        generate(12),
        st,
        optimizer="bootstrap",
        lm=build_heuristic_lm("resume_profile"),
        threads=1,
    )
    assert rep.saved and rep.optimized >= rep.baseline and rep.train + rep.dev == 12
    meta = json.loads(artifacts.artifact_path(st, "resume_profile").read_text())["job_sentry"]
    assert (
            meta["fingerprint"] == RESUME_TASK.fingerprint
            and meta["optimizer"] == "bootstrap"
            and meta["train_size"] == rep.train
    )
    assert StructuredExtractor(RESUME_TASK, st).artifact.id == rep.artifact_id


def test_optimizer_refuses_to_ship_a_worse_prompt(tmp_path):
    from app.ai_features.ai.optimize import compile_task

    class BrokenAfterTraining:
        """Canonical engine: fine for baseline, but invalid after training."""

        def __init__(self):
            self.n = 0

        def complete(self, request):
            from dspy.lm15 import Message, Response, Usage

            from app.ai_features.ai.dspy_engine import _heuristic_response

            self.n += 1
            if self.n <= 3:  # the 3 baseline dev examples
                return _heuristic_response("resume_profile", request)
            return Response(
                id=None,
                model=request.model,
                message=Message.assistant("[[ ## output ## ]]\n{}\n\n[[ ## completed ## ]]"),
                finish_reason="stop",
                usage=Usage(),
            )

    st = S(tmp_path, engine="dspy")
    rep = compile_task(
        RESUME_TASK,
        generate(12),
        st,
        lm=dspy.LM("test/broken", engine=BrokenAfterTraining(), cache=False),
        threads=1,
        min_gain=0.0,
    )
    assert (
            rep.optimized < rep.baseline
            and not rep.saved
            and not artifacts.artifact_path(st, "resume_profile").exists()
    )


def test_cli_check_evaluate_and_production_guard(tmp_path, monkeypatch, capsys):
    from app.ai_features.ai import cli
    from app.ai_features.ai.settings import get_ai_settings

    # Keep this CLI smoke test independent from a developer's production .env.
    monkeypatch.setenv("AI_MODEL", "heuristic")
    monkeypatch.setenv("AI_ENGINE", "pydantic_ai")
    monkeypatch.setenv("AI_ENV", "development")
    # A whitespace value parses as an empty fallback list while overriding .env.
    monkeypatch.setenv("AI_FALLBACK_MODELS", " ")
    monkeypatch.setenv("AI_COMPILED_DIR", str(tmp_path))
    get_ai_settings.cache_clear()

    async def fake_evaluate(samples):
        ex = build_extractor("resume_profile", get_ai_settings())
        scores = [
            SimpleNamespace(total=0.5, fabricated=False, fields={"name": 0.5}) for _ in samples
        ]
        return ex, scores, [0.0 for _ in samples]

    monkeypatch.setattr(cli, "_evaluate", fake_evaluate)
    with pytest.raises(SystemExit) as e:
        cli.main(["check"])
    assert e.value.code == 0 and "OK" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        cli.main(["evaluate", "-n", "5"])
    out = capsys.readouterr().out
    assert e.value.code == 0 and "mean score" in out and "synthetic data" in out
    monkeypatch.setenv("AI_ENV", "production")
    get_ai_settings.cache_clear()
    with pytest.raises(SystemExit) as e:
        cli.main(["check"])
    assert e.value.code == 1 and "FAIL" in capsys.readouterr().out
    get_ai_settings.cache_clear()
