from __future__ import annotations

from enum import StrEnum


class ResumeStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    EXTRACTING = "extracting"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class ApplicationStatus(StrEnum):
    # Phase 5 owns the full lifecycle; Phase 3 only needs these two.
    PROCESSING = "processing"
    APPLIED = "applied"


ALLOWED_TRANSITIONS: dict[ResumeStatus, set[ResumeStatus]] = {
    ResumeStatus.UPLOADED: {
        ResumeStatus.QUEUED,
        ResumeStatus.EXTRACTING,
        ResumeStatus.FAILED,
    },
    ResumeStatus.QUEUED: {
        ResumeStatus.UPLOADED,
        ResumeStatus.EXTRACTING,
        ResumeStatus.FAILED,
    },
    ResumeStatus.EXTRACTING: {ResumeStatus.ANALYZING, ResumeStatus.FAILED},
    ResumeStatus.ANALYZING: {ResumeStatus.COMPLETED, ResumeStatus.FAILED},
    ResumeStatus.COMPLETED: set(),
    ResumeStatus.FAILED: {ResumeStatus.QUEUED},  # manual retry only
}


class InvalidTransition(Exception):
    pass


def assert_transition(current: str, new: str) -> None:
    cur, nxt = ResumeStatus(current), ResumeStatus(new)
    if cur == nxt:
        return
    if nxt not in ALLOWED_TRANSITIONS[cur]:
        raise InvalidTransition(f"{cur.value} -> {nxt.value}")
