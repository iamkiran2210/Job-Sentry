import os
import shutil

import pytest

from app.ai_features.resumes.config import ResumeSettings
from app.ai_features.resumes.errors import FailureCode, PipelineError
from app.ai_features.resumes.parsers import OcrResult, normalize_text, parse_document
from app.ai_features.resumes.validation import DOCX, PDF, PNG

from . import fixtures as fx

_tesseract_cmd = (
                         os.environ.get("RESUMES_TESSERACT_CMD") or ResumeSettings().tesseract_cmd
                 ).strip() or "tesseract"
needs_tesseract = pytest.mark.skipif(
    shutil.which(_tesseract_cmd) is None,
    reason="tesseract not installed or RESUMES_TESSERACT_CMD is not on PATH",
)


def no_ocr(_):
    raise AssertionError("OCR must not run for text-based files")


def test_pdf_text_extraction_skips_ocr(cfg):
    doc = parse_document(fx.make_pdf(), PDF, cfg, no_ocr)
    assert doc.method == "pdf_text" and not doc.ocr_used and doc.page_count == 1
    assert "jane.example@example.com" in doc.text and "Acme Robotics" in doc.text


def test_scanned_pdf_routes_to_ocr(cfg):
    calls = []

    def fake(png):
        calls.append(png[:4])
        return OcrResult("Jane Q. Example\njane.example@example.com\nPython developer", 88.0)

    doc = parse_document(fx.make_scanned_pdf(), PDF, cfg, fake)
    assert calls and doc.method == "pdf_ocr" and doc.ocr_used and doc.ocr_confidence == 88.0


def test_mixed_pdf(cfg):
    import pymupdf

    d = pymupdf.open()
    d.new_page().insert_text((60, 70), "\n".join(fx.RESUME_LINES))
    d.new_page().insert_image(d[0].rect, stream=fx.make_text_image())
    doc = parse_document(
        d.tobytes(), PDF, cfg, lambda b: OcrResult("scanned page text here ok", 70.0)
    )
    assert doc.method == "pdf_mixed"


def test_ocr_disabled_scanned_pdf_has_no_text(cfg):
    off = cfg.model_copy(update={"ocr_enabled": False})
    with pytest.raises(PipelineError) as e:
        parse_document(fx.make_scanned_pdf(), PDF, off, no_ocr)
    assert e.value.code == FailureCode.NO_TEXT_FOUND


def test_encrypted_and_corrupt_pdf(cfg):
    with pytest.raises(PipelineError) as e:
        parse_document(fx.make_encrypted_pdf(), PDF, cfg, no_ocr)
    assert e.value.code == FailureCode.ENCRYPTED_FILE
    with pytest.raises(PipelineError) as e:
        parse_document(b"%PDF-1.4 garbage", PDF, cfg, no_ocr)
    assert e.value.code in (FailureCode.CORRUPT_FILE, FailureCode.NO_TEXT_FOUND)


def test_docx_extraction_includes_header_and_tables(cfg):
    doc = parse_document(fx.make_docx(), DOCX, cfg, no_ocr)
    assert doc.method == "docx_text"
    assert "jane.example@example.com" in doc.text  # header
    assert "Languages | Python, SQL" in doc.text  # table row
    assert doc.text.index("SUMMARY") < doc.text.index("Acme Robotics")  # order preserved


def test_corrupt_docx(cfg):
    with pytest.raises(PipelineError) as e:
        parse_document(b"PK\x03\x04 not really", DOCX, cfg, no_ocr)
    assert e.value.code == FailureCode.CORRUPT_FILE


def test_image_uses_ocr_and_flags_low_confidence(cfg):
    doc = parse_document(
        fx.make_text_image(),
        PNG,
        cfg,
        lambda b: OcrResult("some readable words here for test", 20.0),
    )
    assert doc.method == "image_ocr" and any("low" in w.lower() for w in doc.warnings)


@needs_tesseract
def test_real_tesseract_on_synthetic_image(cfg):
    doc = parse_document(fx.make_text_image(), PNG, cfg)
    assert "jane" in doc.text.lower() and "example" in doc.text.lower()
    assert doc.ocr_confidence and doc.ocr_confidence > 50


@needs_tesseract
def test_real_tesseract_on_scanned_pdf(cfg):
    doc = parse_document(fx.make_scanned_pdf(), PDF, cfg)
    assert doc.method == "pdf_ocr" and "jane" in doc.text.lower()


def test_blank_image_is_no_text(cfg):
    with pytest.raises(PipelineError) as e:
        parse_document(fx.make_text_image(lines=[]), PNG, cfg, lambda b: OcrResult("", None))
    assert e.value.code == FailureCode.NO_TEXT_FOUND


def test_normalize_text():
    assert normalize_text("a\x00b\u00a0 c\n\n\n\nd ﬁ") == "ab c\n\nd fi"
