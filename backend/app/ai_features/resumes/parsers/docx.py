from __future__ import annotations

import io
import re

from ..config import ResumeSettings
from ..errors import FailureCode, PipelineError
from .ocr import OcrFn
from .types import ParsedDocument


def _table_lines(table, depth: int = 0) -> list[str]:
    lines: list[str] = []
    for row in table.rows:
        seen, cells, nested = set(), [], []
        for cell in row.cells:
            if id(cell._tc) in seen:  # merged cells repeat the same element
                continue
            seen.add(id(cell._tc))
            t = " ".join(p.text.strip() for p in cell.paragraphs if p.text.strip())
            if t:
                cells.append(t)
            if depth < 2:
                for inner in cell.tables:
                    nested.extend(_table_lines(inner, depth + 1))
        if cells:
            lines.append(" | ".join(cells))
        lines.extend(nested)
    return lines


def parse_docx(data: bytes, cfg: ResumeSettings, ocr: OcrFn) -> ParsedDocument:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        doc = Document(io.BytesIO(data))
    except Exception:
        raise PipelineError(FailureCode.CORRUPT_FILE) from None

    try:
        parts: list[str] = []
        seen_hdr: set[str] = set()
        for section in doc.sections:  # contact details often live in headers
            for container in (section.header, section.footer):
                t = "\n".join(p.text.strip() for p in container.paragraphs if p.text.strip())
                if t and t not in seen_hdr:
                    seen_hdr.add(t)
                    parts.append(t)
        for child in doc.element.body.iterchildren():  # keeps document order
            if child.tag == qn("w:p"):
                t = Paragraph(child, doc).text.strip()
                if t:
                    parts.append(t)
            elif child.tag == qn("w:tbl"):
                parts.extend(_table_lines(Table(child, doc)))
        text = "\n".join(parts)
        hyperlinks: list[str] = []
        seen_links: set[str] = set()
        for rel in doc.part.rels.values():
            if rel.is_external and "hyperlink" in rel.reltype:
                target = str(getattr(rel, "target_ref", "") or "").strip()
                low = target.casefold()
                if low.startswith(("http://", "https://")):
                    key = low.rstrip("/")
                    if key not in seen_links:
                        seen_links.add(key)
                        hyperlinks.append(target)
                elif low.startswith("mailto:"):
                    addr = target[7:].split("?", 1)[0].strip()
                    if addr and "@" in addr and addr.casefold() not in seen_links:
                        seen_links.add(addr.casefold())
                        hyperlinks.append(addr)
        text_lower = text.casefold()
        missing_links = [
            uri
            for uri in hyperlinks
            if re.sub(r"^https?://(www\.)?", "", uri.casefold()).rstrip("/") not in text_lower
        ]
        if missing_links:
            link_block = "[Embedded Links]\n" + "\n".join(missing_links[:25])
            text = f"{text}\n\n{link_block}" if text else link_block
        images = [
            rel.target_part.blob
            for rel in doc.part.rels.values()
            if "image" in rel.reltype and not rel.is_external
        ]
    except Exception:
        raise PipelineError(FailureCode.CORRUPT_FILE) from None

    warnings: list[str] = []
    if len(re.sub(r"\s", "", text)) >= cfg.min_chars_per_page or not images:
        return ParsedDocument(text=text, method="docx_text", warnings=warnings)

    # Sparse text but embedded pictures: probably a scanned resume pasted into Word.
    if not cfg.ocr_enabled:
        warnings.append("Document is mostly images and OCR is disabled.")
        return ParsedDocument(text=text, method="docx_text", warnings=warnings)
    ocr_texts, confs = [], []
    for blob in images[: cfg.docx_max_ocr_images]:
        try:
            r = ocr(blob)
        except PipelineError as exc:
            if exc.code == FailureCode.CORRUPT_FILE:  # e.g. EMF/WMF vector images
                continue
            raise
        if r.text.strip():
            ocr_texts.append(r.text.strip())
            if r.confidence is not None:
                confs.append(r.confidence)
    if len(images) > cfg.docx_max_ocr_images:
        warnings.append(f"Only the first {cfg.docx_max_ocr_images} embedded images were OCR'd.")
    return ParsedDocument(
        text="\n\n".join([t for t in [text] + ocr_texts if t]),
        method="docx_ocr" if ocr_texts else "docx_text",
        ocr_used=bool(ocr_texts),
        ocr_confidence=(sum(confs) / len(confs)) if confs else None,
        warnings=warnings,
    )
