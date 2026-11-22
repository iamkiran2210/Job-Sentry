import uuid

from app.ai_features.resumes.identity import (
    CandidateSnapshot,
    Signals,
    decide,
    name_relation,
    normalize_email,
    normalize_name,
    normalize_phone,
)


def snap(name=None, email=None, phone=None, applied=False):
    return CandidateSnapshot(
        uuid.uuid4(),
        normalize_name(name),
        normalize_email(email),
        normalize_phone(phone),
        applied,
    )


def sig(name=None, email=None, phone=None):
    return Signals(normalize_name(name), normalize_email(email), normalize_phone(phone))


def test_normalizers():
    assert (
            normalize_email(" Jane@Example.COM ") == "jane@example.com"
            and normalize_email("nope") is None
    )
    assert normalize_phone("+1 (415) 555-0134") == normalize_phone("415.555.0134") == "4155550134"
    assert normalize_phone("123") is None
    assert normalize_name("Dr. José  Álvarez") == "jose alvarez"


def test_name_relations():
    assert name_relation("john smith", "john smith") == "exact"
    assert name_relation("john smith", "john a smith") == "compatible"
    assert name_relation("john smith", "mary jones") == "conflict"
    assert name_relation(None, "john") == "unknown"


def test_new_person_creates_candidate():
    d = decide(sig("Jane Doe", "jane@x.com"), [])
    assert d.action == "create_new" and d.suggestions == []


def test_same_email_compatible_name_links():
    c = snap("Jane Doe", "jane@x.com")
    d = decide(sig("Jane A Doe", "JANE@x.com"), [c])
    assert d.action == "link_existing" and d.candidate_id == c.id


def test_same_email_unknown_name_links():
    c = snap("Jane Doe", "jane@x.com")
    assert decide(sig(None, "jane@x.com"), [c]).action == "link_existing"


def test_email_with_conflicting_name_is_NOT_merged():
    c = snap("Jane Doe", "shared@x.com")
    d = decide(sig("Robert Brown", "shared@x.com"), [c])
    assert d.action == "create_new" and d.suggestions[0].reasons == [
        "email_match",
        "name_conflict",
    ]


def test_phone_only_and_name_only_never_auto_merge():
    c = snap("Jane Doe", "other@x.com", "415 555 0134")
    d = decide(sig("Jane Doe", "new@x.com", "+1 415 555 0134"), [c])
    assert d.action == "create_new" and d.suggestions[0].strength == "weak"
    d2 = decide(sig("Jane Doe"), [snap("Jane Doe")])
    assert d2.action == "create_new" and d2.suggestions[0].reasons == ["name_match_only"]
    assert (
            decide(sig("Madonna"), [snap("Madonna")]).suggestions == []
    )  # single-token names are too weak


def test_ambiguous_multiple_strong_matches_not_merged():
    d = decide(
        sig("Jane Doe", "j@x.com"),
        [snap("Jane Doe", "j@x.com"), snap("Jane Doe", "j@x.com")],
    )
    assert d.action == "create_new" and len(d.suggestions) == 2
    assert all("ambiguous_multiple_matches" in s.reasons for s in d.suggestions)


def test_same_person_same_job_resubmission_is_not_merged():
    c = snap("Jane Doe", "j@x.com", applied=True)
    d = decide(sig("Jane Doe", "j@x.com"), [c])
    assert d.action == "create_new" and "same_job_resubmission" in d.suggestions[0].reasons
