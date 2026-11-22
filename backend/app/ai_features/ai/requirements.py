"""
Phase 2 adapter. Phase 2 loads its provider from AI_REQUIREMENTS_PROVIDER=package.module:factory.
Enable AI requirement suggestions with ONE env var, no Phase 2 code change:

    AI_REQUIREMENTS_PROVIDER=app.ai_features.ai.requirements:build_provider

Returns {"requirements": [{category, name, requirement_type, importance, weight, is_mandatory}, ...]}
(weights are floats 0-1; mandatory => 0; preferred total exactly 1.0), i.e. already valid for the Phase 2
rules. Suggestions only: nothing is persisted here. If your `validate_extraction` expects a different
wrapper shape, adjust `to_payload` below (one place).
"""

from __future__ import annotations

from typing import Any

from app.ai_features.schemas.requirement_suggestions import JobRequirementSuggestions

from .grounding import Haystack
from .tasks import get_extractor


def to_payload(suggestions: JobRequirementSuggestions) -> dict[str, Any]:
    return {
        "requirements": [
            {
                "category": r.category,
                "name": r.name,
                "requirement_type": r.requirement_type,
                "importance": r.importance,
                "weight": r.weight,
                "is_mandatory": r.requirement_type == "mandatory",
            }
            for r in suggestions.suggestions
        ]
    }


class AIRequirementProvider:
    async def extract_requirements(self, description: str) -> dict[str, Any]:
        from .errors import AIError
        from .settings import AISettings
        from .tasks import build_extractor

        try:
            run = await get_extractor("job_requirements").run(description)
        except AIError:
            run = await build_extractor(
                "job_requirements",
                AISettings(_env_file=None, model="heuristic", fallback_models=""),
            ).run(description)
        hay = Haystack(description)
        # never-invent rule: keep only requirements whose evidence quote (or name) is really in the description
        grounded = [
            r
            for r in run.output.suggestions
            if (r.evidence and hay.has(r.evidence)) or hay.has_loose(r.name)
        ]
        return to_payload(JobRequirementSuggestions(suggestions=grounded).normalized())


def build_provider() -> AIRequirementProvider:
    return AIRequirementProvider()
