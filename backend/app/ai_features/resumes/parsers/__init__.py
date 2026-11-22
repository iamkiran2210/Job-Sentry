from __future__ import annotations

import re
import unicodedata

from ..config import ResumeSettings
from ..errors import FailureCode, PipelineError
from ..validation import DOCX, IMAGE_TYPES, PDF
from .docx import parse_docx
from .ocr import OcrFn, default_ocr
from .pdf import parse_pdf
from .types import OcrResult, ParsedDocument

__all__ = ["parse_document", "normalize_text", "ParsedDocument", "OcrResult", "OcrFn"]


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\x00", "")
    text = re.sub(r"[^\S\n]+", " ", text)
    text = "".join(ch for ch in text if ch == "\n" or ch.isprintable())
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_document(
        data: bytes, content_type: str, cfg: ResumeSettings, ocr: OcrFn | None = None
) -> ParsedDocument:
    """Route to the right parser. Sync/CPU-bound: run in a worker, not the request path."""
    ocr = ocr or default_ocr(cfg)
    if content_type == PDF:
        doc = parse_pdf(data, cfg, ocr)
    elif content_type == DOCX:
        doc = parse_docx(data, cfg, ocr)
    elif content_type in IMAGE_TYPES:
        if not cfg.ocr_enabled:
            raise PipelineError(FailureCode.OCR_UNAVAILABLE)
        r = ocr(data)
        doc = ParsedDocument(
            text=r.text,
            method="image_ocr",
            page_count=1,
            ocr_used=True,
            ocr_confidence=r.confidence,
        )
    else:
        raise PipelineError(FailureCode.UNSUPPORTED_CONTENT)

    doc.text = normalize_text(doc.text)
    if len(re.sub(r"\s", "", doc.text)) < 20:
        raise PipelineError(FailureCode.NO_TEXT_FOUND)
    if len(doc.text) > cfg.max_text_chars:
        doc.text = doc.text[: cfg.max_text_chars]
        doc.warnings.append("Text was truncated to the maximum length.")
    if doc.ocr_confidence is not None and doc.ocr_confidence < cfg.ocr_low_confidence:
        doc.warnings.append("OCR confidence is low; extracted data may be unreliable.")
    return doc
