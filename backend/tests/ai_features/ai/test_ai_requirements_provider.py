"""Phase 2 adapter: AI_REQUIREMENTS_PROVIDER=app.ai_features.ai.requirements:build_provider"""

import importlib

import pytest

from app.ai_features.ai.requirements import build_provider
from app.ai_features.schemas.requirement_suggestions import (
    JobRequirementSuggestions,
    SuggestedRequirement,
)

DESC = """Backend Engineer
Requirements:
- 5+ years of Python
- Bachelor degree in Computer Science
Nice to have:
- Kubernetes
- Terraform
- Redis
Responsibilities:
- Build and operate APIs
"""


def test_factory_is_loadable_the_way_phase2_loads_it():
    mod, _, name = "app.ai_features.ai.requirements:build_provider".partition(":")
    provider = getattr(importlib.import_module(mod), name)()
    assert callable(provider.extract_requirements)


@pytest.mark.asyncio
async def test_payload_satisfies_phase2_rules(monkeypatch):
    # Exercise the adapter contract without calling the deployment model from .env.
    import app.ai_features.ai.requirements as mod

    class Fake:
        async def run(self, _text):
            from types import SimpleNamespace

            return SimpleNamespace(
                output=JobRequirementSuggestions(
                    requirements=[
                        SuggestedRequirement(
                            category="experience",
                            name="5+ years of Python",
                            requirement_type="mandatory",
                            evidence="5+ years of Python",
                        ),
                        SuggestedRequirement(
                            category="education",
                            name="Bachelor degree in Computer Science",
                            requirement_type="mandatory",
                            evidence="Bachelor degree in Computer Science",
                        ),
                        *[
                            SuggestedRequirement(
                                category="skills",
                                name=skill,
                                requirement_type="preferred",
                                evidence=skill,
                            )
                            for skill in ("Kubernetes", "Terraform", "Redis")
                        ],
                        SuggestedRequirement(
                            category="responsibility",
                            name="Build and operate APIs",
                            requirement_type="preferred",
                            evidence="Build and operate APIs",
                        ),
                    ]
                )
            )

    monkeypatch.setattr(mod, "get_extractor", lambda _name: Fake())
    out = await build_provider().extract_requirements(DESC)
    reqs = out["requirements"]
    assert reqs and all(
        set(r)
        == {
            "category",
            "name",
            "requirement_type",
            "importance",
            "weight",
            "is_mandatory",
        }
        for r in reqs
    )
    for r in reqs:
        assert r["is_mandatory"] == (r["requirement_type"] == "mandatory")
        assert (r["weight"] == 0.0) if r["is_mandatory"] else (0 < r["weight"] <= 1)
    pref = [r["weight"] for r in reqs if not r["is_mandatory"]]
    assert pref and abs(sum(pref) - 1.0) < 1e-9  # preferred weights total exactly 1
    assert not any(
        "evidence" in r for r in reqs
    )  # internal grounding field never leaks into suggestions


@pytest.mark.asyncio
async def test_invented_requirements_are_dropped(monkeypatch):
    import app.ai_features.ai.requirements as mod

    class Fake:
        async def run(self, text):
            from types import SimpleNamespace

            return SimpleNamespace(
                output=JobRequirementSuggestions(
                    requirements=[
                        SuggestedRequirement(
                            name="Python",
                            requirement_type="mandatory",
                            evidence="Python",
                        ),
                        SuggestedRequirement(
                            name="Quantum computing PhD",
                            requirement_type="mandatory",
                            evidence="a PhD in quantum computing",
                        ),
                    ]
                )
            )

    monkeypatch.setattr(mod, "get_extractor", lambda name: Fake())
    out = await mod.build_provider().extract_requirements("We need Python.")
    assert [r["name"] for r in out["requirements"]] == ["Python"]


def test_weight_normalization_edge_cases():
    n = lambda *rs: JobRequirementSuggestions(requirements=list(rs)).normalized().requirements  # noqa: E731
    only_mandatory = n(SuggestedRequirement(name="A", requirement_type="mandatory", weight=0.7))
    assert only_mandatory[0].weight == 0.0
    three = n(*[SuggestedRequirement(name=x, importance="high") for x in "ABC"])
    assert sum(r.weight for r in three) == pytest.approx(1.0) and all(
        0 < r.weight < 1 for r in three
    )
    dup = n(SuggestedRequirement(name="Go"), SuggestedRequirement(name="go"))
    assert len(dup) == 1 and dup[0].weight == 1.0
