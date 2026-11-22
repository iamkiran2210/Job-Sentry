from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OcrResult:
    text: str
    confidence: float | None  # mean word confidence, 0-100


@dataclass
class ParsedDocument:
    text: str
    method: str  # pdf_text | pdf_ocr | pdf_mixed | docx_text | docx_ocr | image_ocr
    page_count: int | None = None
    ocr_used: bool = False
    ocr_confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
