from app.ai_features.schemas.resume_extraction import ExtractedProfileData
from app.ai_features.resumes.grounding import ground_profile

from . import fixtures as fx


def parse(d):
    return ExtractedProfileData.model_validate(d)


def test_unknown_stays_null_and_junk_is_tolerated():
    p = parse(
        {
            "full_name": None,
            "contact": None,
            "skills": ["Python", {"name": None}, {"name": "python"}, 5],
            "employment": [{"company": "X", "start_date": "last spring", "end_date": "2020-13"}],
            "bad_field": "ignored",
            "experience_claims": [{"years": 999, "statement": "lots"}],
        }
    )
    assert p.full_name.value is None and p.contact.email.value is None
    assert [s.name for s in p.skills] == ["Python"]  # dedup + dropped nameless/non-dict
    assert p.employment[0].start_date is None and p.employment[0].end_date is None  # not invented
    assert p.experience_claims[0].years is None
    assert p.education == [] and p.certifications == [] and p.projects == []


def test_confidence_out_of_range_becomes_null_and_lists_capped():
    p = parse({"skills": [{"name": f"s{i}", "confidence": 7} for i in range(500)]})
    assert len(p.skills) == 150 and p.skills[0].confidence is None


def test_grounding_keeps_traceable_values():
    p, warnings = ground_profile(parse(fx.profile_dict()), fx.RESUME_TEXT)
    assert p.contact.email.value == "jane.example@example.com"
    assert p.contact.phone.value == "+1 415 555 0134"
    assert {s.name for s in p.skills} == {"Python", "FastAPI"}
    assert p.employment and p.education and p.certifications and p.projects and p.experience_claims
    assert warnings == []


def test_grounding_removes_fabricated_values():
    d = fx.profile_dict()
    d["contact"]["email"]["value"] = "made.up@nowhere.com"
    d["contact"]["phone"]["value"] = "+1 999 000 1111"
    d["contact"]["github_url"] = {"value": "https://github.com/ghost"}
    d["full_name"]["value"] = "Totally Different"
    d["skills"].append({"name": "Kubernetes"})
    d["employment"].append({"company": "Google", "title": "CEO"})
    d["certifications"].append({"name": "Fake Cert Pro"})
    p, warnings = ground_profile(parse(d), fx.RESUME_TEXT)
    assert p.contact.email.value is None and p.contact.phone.value is None
    assert p.contact.github_url.value is None and p.full_name.value is None
    assert "Kubernetes" not in {s.name for s in p.skills}
    assert [e.company for e in p.employment] == ["Acme Robotics"]
    assert [c.name for c in p.certifications] == ["AWS Certified Developer"]
    assert len(warnings) >= 5


def test_ungrounded_evidence_is_cleared_and_confidence_capped():
    d = fx.profile_dict()
    d["skills"][0]["evidence"] = "an invented sentence that is not in the resume"
    d["skills"][0]["confidence"] = 0.99
    p, warnings = ground_profile(parse(d), fx.RESUME_TEXT)
    py = next(s for s in p.skills if s.name == "Python")
    assert py.evidence is None and py.confidence <= 0.4
    assert any("evidence" in w for w in warnings)


def test_short_skill_names_need_word_boundaries():
    p, _ = ground_profile(
        parse({"skills": [{"name": "C"}, {"name": "R"}]}),
        "Experienced in Docker and Python",
    )
    assert p.skills == []
