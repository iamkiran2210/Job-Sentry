"""Regression & fine-tuning tests for resume & job-requirement extraction quality."""

from __future__ import annotations

import pymupdf
from app.ai_features.ai.grounding import Haystack
from app.ai_features.ai.heuristic import extract_resume
from app.ai_features.ai.skill_extraction import (
    DescriptionToSkillsWorkflow,
    RecommendationSchema,
    Suggestion,
    SuggestionData,
)
from app.ai_features.ai.tasks import REQUIREMENTS_TASK, RESUME_TASK
from app.ai_features.resumes.config import ResumeSettings
from app.ai_features.resumes.grounding import ground_profile
from app.ai_features.resumes.parsers.ocr import _order_ocr_blocks, _split_line_segments
from app.ai_features.resumes.parsers.pdf import parse_pdf
from app.ai_features.schemas.resume_extraction import ExtractedProfileData


def test_asymmetric_two_column_pdf_keeps_wide_left_blocks_in_column_order():
    """Canva/LaTeX 65/35 resumes must not rip wide left-column blocks down to the bottom."""
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    # Wide left column (~62% width: x=30..380)
    page.insert_text((30, 80), "C KIRAN BABU\nB.Tech (Computer Science)")
    page.insert_text((30, 140), "Career Objective")
    page.insert_text(
        (30, 170),
        "To secure a challenging role in software engineering and machine learning systems.",
    )
    page.insert_text((30, 250), "Education\nBachelor Of Technology")
    page.insert_text((30, 290), "Siddharth Institute of Technology & Engineering, Puttur")
    page.insert_text((30, 320), "2023 - 2027 | CGPA: 9.05")
    # Narrow right sidebar (~32% width: x=410..580)
    page.insert_text((410, 140), "Details\n+91 8374841866\nkiran@example.com")
    page.insert_text((410, 250), "Technical Skills\nPython\nLinux\nSQL")
    pdf_bytes = doc.tobytes()
    doc.close()

    parsed = parse_pdf(pdf_bytes, ResumeSettings(_env_file=None, ocr_enabled=False), ocr=lambda _: None)
    # Wide left-column blocks stay inside left column BEFORE right sidebar "Details" / "Technical Skills"
    assert parsed.text.index("Career Objective") < parsed.text.index("To secure a challenging role")
    assert parsed.text.index("To secure a challenging role") < parsed.text.index("Details")
    assert parsed.text.index("Bachelor Of Technology") < parsed.text.index("Siddharth Institute")
    assert parsed.text.index("Siddharth Institute") < parsed.text.index("Technical Skills")


def test_ocr_horizontal_gap_splitter_separates_interleaved_two_column_lines():
    # Words on the same visual y-line from left column (x=40..280) and right column (x=460..850)
    words = [
        (40.0, 200.0, 130.0, 220.0, "Languages:"),
        (140.0, 200.0, 210.0, 220.0, "Python,"),
        (220.0, 200.0, 260.0, 220.0, "SQL"),
        (460.0, 200.0, 560.0, 220.0, "Built"),
        (570.0, 200.0, 680.0, 220.0, "scalable"),
        (690.0, 200.0, 820.0, 220.0, "pipelines"),
    ]
    segs = _split_line_segments(words, page_width=1000.0)
    assert len(segs) == 2
    assert segs[0][4] == "Languages: Python, SQL"
    assert segs[1][4] == "Built scalable pipelines"

    # Asymmetric 65/35 blocks order cleanly without straddling blocks dropping to bottom
    blocks = [
        (0, 40.0, 20.0, 960.0, 70.0, ["JANE DOE"]),
        (1, 40.0, 120.0, 620.0, 220.0, ["SUMMARY", "ML Engineer"]),
        (2, 40.0, 260.0, 620.0, 380.0, ["EDUCATION", "B.Tech CS"]),
        (3, 670.0, 120.0, 960.0, 220.0, ["CONTACT", "jane@example.com"]),
        (4, 670.0, 260.0, 960.0, 380.0, ["SKILLS", "Python, PyTorch"]),
    ]
    ordered = [" ".join(g) for g in _order_ocr_blocks(blocks, page_width=1000.0)]
    assert ordered == [
        "JANE DOE",
        "SUMMARY ML Engineer",
        "EDUCATION B.Tech CS",
        "CONTACT jane@example.com",
        "SKILLS Python, PyTorch",
    ]


def test_grounding_cleans_ocr_names_emails_watermarks_phones_and_project_urls():
    # 1. Malformed OCR email is rejected; OCR kerning name "J ohn Doe" is repaired; year range rejected as phone
    source = (
        "J ohn Doe | 2017 - 2021\n"
        "martabano jeffSgmail.com\n"
        "www.qwikresume.com | support@qwikresume.com\n"
        "https://www.udemy.com/certificate/UC-7afd5d1b/\n"
        "github.com/johndoe\n"
        "Projects:\n"
        "Resume AI — https://github.com/johndoe/resume-ai\n"
        "Skills: C++17, Amazon Web Services, Scikit-learn, Python\n"
    )
    raw = {
        "full_name": {"value": "J ohn Doe", "confidence": 0.8, "evidence": "J ohn Doe"},
        "contact": {
            "email": {"value": "martabano jeffSgmail.com", "confidence": 0.72, "evidence": "martabano jeffSgmail.com"},
            "phone": {"value": "2017 - 2021", "confidence": 0.6, "evidence": "2017 - 2021"},
            "portfolio_url": {"value": "www.qwikresume.com", "confidence": 0.78, "evidence": "www.qwikresume.com"},
            "github_url": {"value": "github.com/johndoe", "confidence": 0.9, "evidence": "github.com/johndoe"},
        },
        "skills": [
            {"name": "</> C++", "evidence": "C++17"},
            {"name": "AWS", "evidence": "Amazon Web Services"},
            {"name": "Scikit-learn Expert", "evidence": "Scikit-learn"},
            {"name": "Scikit learn", "evidence": "Scikit-learn"},
            {"name": "Loaded and unloaded vehicles carefully every single morning", "evidence": "Python"},
        ],
        "projects": [
            {"name": "Resume AI", "url": "github.com/johndoe/resume-ai", "evidence": "Resume AI"},
            {"name": "Resume AI", "url": "https://evil-invented.example/repo", "evidence": "Resume AI"},
        ],
    }
    parsed = ExtractedProfileData.model_validate(raw)
    grounded, warnings = ground_profile(parsed, source)

    assert grounded.full_name.value == "John Doe"
    assert grounded.contact.email.value is None  # malformed OCR email removed
    assert grounded.contact.phone.value is None  # year range removed
    assert grounded.contact.portfolio_url.value is None  # template watermark removed
    assert grounded.contact.github_url.value == "https://github.com/johndoe"
    assert [s.name for s in grounded.skills] == ["C++", "AWS", "Scikit-learn"]
    assert grounded.projects[0].url == "https://github.com/johndoe/resume-ai"
    assert grounded.projects[1].url is None
    assert len(warnings) >= 4


def test_grounding_accepts_llm_repaired_ocr_email_and_rejects_template_email_and_cert_portfolio():
    source = (
        "Jeff Martabano\n"
        "martabano jeffSgmail.com\n"
        "support@qwikresume.com\n"
        "linkedin.com/in/jeff-martabano\n"
        "https://www.udemy.com/certificate/UC-12345/\n"
    )
    # LLM repaired the OCR email -> Haystack.has_email accepts it!
    p1 = ExtractedProfileData.model_validate(
        {
            "full_name": {"value": "Jeff Martabano"},
            "contact": {
                "email": {"value": "martabano.jeff@gmail.com"},
                "portfolio_url": {"value": "linkedin.com/in/jeff-martabano"},
            },
        }
    )
    g1, _ = ground_profile(p1, source)
    assert g1.contact.email.value == "martabano.jeff@gmail.com"
    assert g1.contact.linkedin_url.value == "https://linkedin.com/in/jeff-martabano"
    assert g1.contact.portfolio_url.value is None

    # Template support email + certificate URL as portfolio are both dropped
    p2 = ExtractedProfileData.model_validate(
        {
            "full_name": {"value": "RESUME"},
            "contact": {
                "email": {"value": "support@qwikresume.com"},
                "portfolio_url": {"value": "https://www.udemy.com/certificate/UC-12345/"},
            },
        }
    )
    g2, _ = ground_profile(p2, source)
    assert g2.full_name.value is None
    assert g2.contact.email.value is None
    assert g2.contact.portfolio_url.value is None


def test_schema_normalizes_extended_dates_entities_and_degree_fields():
    raw = {
        "full_name": {"value": "C KIRAN BABU,"},
        "employment": [
            {
                "company": "Maple Leaf Consulting,",
                "title": "€ Python Developer",
                "start_date": "Jan / 2021",
                "end_date": "Ongoing",
            },
            {
                "company": "Acme Corp",
                "title": "Intern",
                "start_date": "May '20",
                "end_date": "2020/Dec",
            },
        ],
        "education": [
            {
                "institution": "Siddharth Institute of Technology & Engineering,",
                "degree": "B.Tech (Computer Science)",
                "start_date": "2023",
                "end_date": "Expected May 2027",
            }
        ],
    }
    parsed = ExtractedProfileData.model_validate(raw)
    assert parsed.full_name.value == "C KIRAN BABU"
    assert parsed.employment[0].company == "Maple Leaf Consulting"
    assert parsed.employment[0].title == "Python Developer"
    assert parsed.employment[0].start_date == "2021-01"
    assert parsed.employment[0].end_date is None
    assert parsed.employment[0].is_current is True
    assert parsed.employment[1].start_date == "2020-05"
    assert parsed.employment[1].end_date == "2020-12"
    assert parsed.education[0].institution == "Siddharth Institute of Technology & Engineering"
    assert parsed.education[0].end_date == "2027-05"

    source = (
        "C KIRAN BABU\nMaple Leaf Consulting Python Developer\nAcme Corp Intern\n"
        "Siddharth Institute of Technology & Engineering B.Tech (Computer Science)"
    )
    grounded, _ = ground_profile(parsed, source)
    assert grounded.full_name.value == "C KIRAN BABU"
    assert grounded.education[0].degree == "B.Tech"
    assert grounded.education[0].field_of_study == "Computer Science"


def test_heuristic_fallback_handles_all_caps_initials_mid_doc_phone_and_skill_prefixes():
    text = (
        "RESUME\n"
        "C KIRAN BABU\n"
        "Education\n"
        "B.Tech, Siddharth Institute, 2023 - 2027\n"
        "Details\n"
        "+91 8374841866\n"
        "support@qwikresume.com\n"
        "kiranbabu@gmail.com\n"
        "www.qwikresume.com\n"
        "Technical Skills\n"
        "Languages: Python, SQL\n"
        "Hand-Eye Coordination Expert\n"
    )
    out = extract_resume(text)
    assert out["full_name"]["value"] == "C KIRAN BABU"
    assert out["contact"]["email"]["value"] == "kiranbabu@gmail.com"
    assert out["contact"]["phone"]["value"] == "+91 8374841866"
    assert "portfolio_url" not in out["contact"]
    skill_names = [s["name"] for s in out["skills"]]
    assert "Python" in skill_names
    assert "SQL" in skill_names
    assert "Hand-Eye Coordination" in skill_names


def test_skill_extraction_grounds_deduplicates_and_task_budgets_prevent_truncation():
    assert RESUME_TASK.max_output_tokens >= 8192
    assert REQUIREMENTS_TASK.max_output_tokens >= 4096

    desc = "We require 5+ years of Python, FastAPI, PostgreSQL, and Amazon Web Services."
    raw_out = RecommendationSchema(
        data=SuggestionData(
            suggestions=[
                Suggestion(category="skills", name="Python", requirement_type="mandatory", importance="high"),
                Suggestion(category="skills", name="python", requirement_type="preferred", importance="low"),
                Suggestion(category="skills", name="AWS", requirement_type="preferred", importance="high"),
                Suggestion(category="skills", name="Quantum Teleportation", requirement_type="preferred",
                           importance="low"),
            ]
        )
    )
    cleaned = DescriptionToSkillsWorkflow._ground_and_dedupe(raw_out, desc)
    names = [s.name for s in cleaned.data.suggestions]
    assert names == ["Python", "AWS"]
    assert Haystack(desc).has_skill("AWS")
