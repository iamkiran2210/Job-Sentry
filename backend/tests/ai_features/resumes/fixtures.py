"""Synthetic documents only. No real applicant data."""

from __future__ import annotations

import io

RESUME_LINES = [
    "Jane Q. Example",
    "jane.example@example.com | +1 415 555 0134 | Springfield",
    "SUMMARY",
    "Backend engineer with 5+ years of Python experience.",
    "SKILLS",
    "Python, FastAPI, PostgreSQL, Docker",
    "EXPERIENCE",
    "Backend Engineer, Acme Robotics, 2019-03 to Present",
    "Built inventory APIs serving internal teams.",
    "EDUCATION",
    "BSc Computer Science, Example University, 2018",
    "CERTIFICATIONS",
    "AWS Certified Developer",
    "PROJECTS",
    "Inventory Tracker - FastAPI service for warehouse stock",
]
RESUME_TEXT = "\n".join(RESUME_LINES)


def make_pdf(lines=RESUME_LINES) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 70), "\n".join(lines), fontsize=11)
    return doc.tobytes()


def make_encrypted_pdf() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((60, 70), "secret " * 20)
    return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")


def make_text_image(lines=RESUME_LINES[:6], fmt="PNG", size=(1600, 700)) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=34)
    for i, line in enumerate(lines):
        d.text((40, 30 + i * 60), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


def make_scanned_pdf() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=make_text_image())
    return doc.tobytes()


def make_docx(with_table=True) -> bytes:
    from docx import Document

    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "Jane Q. Example | jane.example@example.com"
    for line in RESUME_LINES[2:6]:
        doc.add_paragraph(line)
    if with_table:
        t = doc.add_table(rows=1, cols=2)
        t.rows[0].cells[0].text = "Languages"
        t.rows[0].cells[1].text = "Python, SQL"
    doc.add_paragraph("Backend Engineer, Acme Robotics, 2019-03 to Present")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_macro_docx() -> bytes:
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<doc/>")
        z.writestr("word/vbaProject.bin", b"x")
    return buf.getvalue()


def make_zip_bomb_docx() -> bytes:
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<doc/>")
        z.writestr("word/big.bin", b"\0" * (120 * 1024 * 1024))
    return buf.getvalue()


def profile_dict(**over) -> dict:
    """What a well-behaved LLM would return for RESUME_TEXT."""
    d = {
        "full_name": {
            "value": "Jane Q. Example",
            "confidence": 0.99,
            "evidence": "Jane Q. Example",
        },
        "contact": {
            "email": {
                "value": "jane.example@example.com",
                "confidence": 0.99,
                "evidence": "jane.example@example.com",
            },
            "phone": {
                "value": "+1 415 555 0134",
                "confidence": 0.95,
                "evidence": "+1 415 555 0134",
            },
            "location": {"value": "Springfield", "confidence": 0.7},
        },
        "skills": [
            {
                "name": "Python",
                "confidence": 0.95,
                "evidence": "Python, FastAPI, PostgreSQL, Docker",
            },
            {"name": "FastAPI", "confidence": 0.9},
        ],
        "employment": [
            {
                "company": "Acme Robotics",
                "title": "Backend Engineer",
                "start_date": "2019-03",
                "is_current": True,
                "confidence": 0.9,
                "evidence": "Backend Engineer, Acme Robotics, 2019-03 to Present",
            }
        ],
        "experience_claims": [
            {
                "statement": "5+ years of Python experience",
                "area": "Python",
                "years": 5,
                "confidence": 0.8,
                "evidence": "5+ years of Python experience",
            }
        ],
        "education": [
            {
                "institution": "Example University",
                "degree": "BSc",
                "field_of_study": "Computer Science",
                "end_date": "2018",
            }
        ],
        "certifications": [{"name": "AWS Certified Developer"}],
        "projects": [{"name": "Inventory Tracker", "technologies": ["FastAPI"]}],
    }
    d.update(over)
    return d
