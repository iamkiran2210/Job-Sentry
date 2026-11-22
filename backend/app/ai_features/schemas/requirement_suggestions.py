"""Structured output for AI job-requirement extraction (Phase 2 suggestions).
Mirrors the Phase 2 rules: mandatory => weight 0; preferred weights are 0-1 and total 1."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

Category = Literal[
    "skills",
    "experience",
    "education",
    "certification",
    "language",
    "responsibility",
    "other",
]
Importance = Literal["low", "medium", "high"]


def _name(v):
    return str(v).strip()[:255] if v is not None else v


class SuggestedRequirement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    category: Category = "other"
    name: Annotated[str, BeforeValidator(_name)]
    requirement_type: Literal["mandatory", "preferred"] = "preferred"
    importance: Importance = "medium"
    weight: float = 0.0
    evidence: str | None = (
        None  # verbatim quote from the description; verified, then stripped before returning
    )


class JobRequirementSuggestions(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    suggestions: list[SuggestedRequirement] = Field(
        default_factory=list,
        validation_alias=AliasChoices("suggestions", "requirements"),
    )

    @property
    def requirements(self) -> list[SuggestedRequirement]:
        return self.suggestions

    @model_validator(mode="before")
    @classmethod
    def _lenient(cls, v):
        if isinstance(v, list):
            return {"suggestions": v}
        return {} if v is None else v

    def normalized(self) -> "JobRequirementSuggestions":
        """Dedupe, force mandatory weight 0, scale preferred weights so they total exactly 1.0."""
        seen, items = set(), []
        for r in self.suggestions:
            key = (r.category, r.name.casefold())
            if r.name and key not in seen:
                seen.add(key)
                items.append(r)
        pref = [r for r in items if r.requirement_type == "preferred"]
        for r in items:
            if r.requirement_type == "mandatory":
                r.weight = 0.0
        if pref:
            raw = [
                r.weight
                if r.weight and r.weight > 0
                else {"high": 3, "medium": 2, "low": 1}[r.importance]
                for r in pref
            ]
            total = sum(raw)
            bps = [max(1, int(round((w / total) * 10000))) for w in raw]
            bps[0] += 10000 - sum(bps)
            for r, b in zip(pref, bps):
                r.weight = round(b / 10000.0, 4)
        return JobRequirementSuggestions(suggestions=items)
