from __future__ import annotations

from typing import Any

from app.modules.candidate_intelligence.ranking.decision_agents import (
    attach_active_decision,
    normalize_agent_id,
)


def rank_rows(
        rows: list[dict[str, Any]],
        offset: int = 0,
        limit: int = 50,
        eligibility: str | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        status: str | None = None,
        verification_status: str | None = None,
        decision_agent: str | None = None,
        decision: str | None = None,
        min_accept_threshold: float | None = None,
) -> list[dict[str, Any]]:
    active_agent = normalize_agent_id(decision_agent)
    selected = []
    for raw_row in rows:
        row = attach_active_decision(
            raw_row, active_agent, min_accept_threshold=min_accept_threshold
        )
        score = row.get("score")
        if eligibility and row.get("eligibility") != eligibility:
            continue
        if min_score is not None and (score is None or score < min_score):
            continue
        if max_score is not None and (score is None or score > max_score):
            continue
        if status and row.get("status") != status:
            continue
        if verification_status and verification_status not in row.get("verification_statuses", []):
            continue
        if decision and (row.get("decision") or {}).get("decision") != decision:
            continue
        selected.append(row)
    selected.sort(
        key=lambda r: (
            -(float(r.get("score")) if r.get("score") is not None else -1),
            {"eligible": 0, "needs_review": 1, "potentially_ineligible": 2}.get(
                r.get("eligibility"), 3
            ),
            -(float(r.get("skills_score")) if r.get("skills_score") is not None else -1),
            -(float(r.get("data_completeness")) if r.get("data_completeness") is not None else -1),
            str(r.get("application_created_at", "")),
            str(r.get("application_id", "")),
        )
    )
    for i, row in enumerate(selected, 1):
        row["rank"] = i
    return selected[offset: offset + limit]
