import pytest

from app.ai_features.resumes.enums import (
    InvalidTransition,
    ResumeStatus as S,
    assert_transition,
)


def test_happy_path_and_retry():
    for a, b in [
        (S.UPLOADED, S.QUEUED),
        (S.QUEUED, S.EXTRACTING),
        (S.EXTRACTING, S.ANALYZING),
        (S.ANALYZING, S.COMPLETED),
        (S.ANALYZING, S.FAILED),
        (S.FAILED, S.QUEUED),
    ]:
        assert_transition(a, b)


@pytest.mark.parametrize(
    "a,b",
    [
        (S.COMPLETED, S.QUEUED),
        (S.COMPLETED, S.FAILED),
        (S.FAILED, S.COMPLETED),
        (S.UPLOADED, S.COMPLETED),
        (S.EXTRACTING, S.QUEUED),
        (S.FAILED, S.EXTRACTING),
    ],
)
def test_illegal(a, b):
    with pytest.raises(InvalidTransition):
        assert_transition(a, b)
