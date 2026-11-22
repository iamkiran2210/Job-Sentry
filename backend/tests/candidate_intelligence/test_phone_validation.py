from app.modules.candidate_intelligence.verification.checks import phone_check


def test_possible_but_invalid_phone_needs_review():
    result = phone_check("+1 (555) 123-4567")

    assert result.status == "needs_review"
    assert result.details["reason_code"] == "possible_not_valid"
