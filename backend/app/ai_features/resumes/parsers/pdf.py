from __future__ import annotations

import re

from ..config import ResumeSettings
from ..errors import FailureCode, PipelineError
from .ocr import OcrFn
from .types import ParsedDocument

try:
    import pymupdf
except ImportError:  # older PyMuPDF
    import fitz as pymupdf  # type: ignore

_LIGATURES = str.maketrans(
    {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\u00a0": " ",
    }
)


def _normalize_pdf_text(text: str) -> str:
    return text.translate(_LIGATURES).strip()


def _extract_layout_aware_text(page) -> str:
    """Preserve reading order on 2-column resumes (Canva/LaTeX) without interleaving columns."""
    try:
        blocks = page.get_text("blocks")
    except Exception:
        return _normalize_pdf_text(page.get_text("text"))

    text_blocks = [
        (float(b[0]), float(b[1]), float(b[2]), float(b[3]), _normalize_pdf_text(str(b[4])))
        for b in blocks
        if len(b) >= 5 and (len(b) < 7 or b[6] == 0) and str(b[4]).strip()
    ]
    if not text_blocks:
        return _normalize_pdf_text(page.get_text("text"))

    page_width = float(getattr(page.rect, "width", 0.0) or 0.0)
    if page_width <= 0:
        text_blocks.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))
        return "\n".join(b[4] for b in text_blocks)

    # Detect genuine two-column pages: multiple non-spanning blocks strictly left AND strictly right
    # of a vertical gutter near the middle of the page.
    best_split: float | None = None
    best_count = 0
    for frac in (0.35, 0.42, 0.50, 0.58):
        split_x = page_width * frac
        left = [b for b in text_blocks if b[2] <= split_x + 8.0]
        right = [b for b in text_blocks if b[0] >= split_x - 8.0]
        if len(left) >= 2 and len(right) >= 2:
            # Verify vertical overlap between left and right columns (not just stacked blocks).
            left_y = (min(b[1] for b in left), max(b[3] for b in left))
            right_y = (min(b[1] for b in right), max(b[3] for b in right))
            overlap = min(left_y[1], right_y[1]) - max(left_y[0], right_y[0])
            if overlap > 40.0 and (len(left) + len(right)) > best_count:
                best_count = len(left) + len(right)
                best_split = split_x

    if best_split is None:
        text_blocks.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))
        return "\n".join(b[4] for b in text_blocks)

    spanning_top = []
    left_col = []
    right_col = []
    spanning_bottom = []
    col_top_y = min(
        b[1]
        for b in text_blocks
        if b[2] <= best_split + 8.0 or b[0] >= best_split - 8.0
    )
    for b in text_blocks:
        if b[2] <= best_split + 8.0:
            left_col.append(b)
        elif b[0] >= best_split - 8.0:
            right_col.append(b)
        elif b[1] <= col_top_y + 10.0:
            spanning_top.append(b)
        else:
            spanning_bottom.append(b)

    for group in (spanning_top, left_col, right_col, spanning_bottom):
        group.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))

    ordered = [*spanning_top, *left_col, *right_col, *spanning_bottom]
    return "\n".join(b[4] for b in ordered)


def _extract_page_links(page) -> list[str]:
    """Extract external HTTP(S)/mailto URI annotations hidden behind clickable text."""
    urls: list[str] = []
    try:
        for link in page.get_links() or []:
            uri = str(link.get("uri") or "").strip()
            if not uri:
                continue
            low = uri.casefold()
            if low.startswith(("http://", "https://")):
                urls.append(uri)
            elif low.startswith("mailto:"):
                addr = uri[7:].split("?", 1)[0].strip()
                if addr and "@" in addr:
                    urls.append(addr)
    except Exception:
        pass
    return urls


def parse_pdf(data: bytes, cfg: ResumeSettings, ocr: OcrFn) -> ParsedDocument:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise PipelineError(FailureCode.CORRUPT_FILE) from None

    warnings: list[str] = []
    pages_text: list[str] = []
    embedded_links: list[str] = []
    seen_links: set[str] = set()
    native = ocr_pages = 0
    confs: list[float] = []
    with doc:
        if doc.needs_pass:
            raise PipelineError(FailureCode.ENCRYPTED_FILE)
        total = doc.page_count
        if total > cfg.pdf_max_pages:
            warnings.append(f"Only the first {cfg.pdf_max_pages} of {total} pages were processed.")
        for index in range(min(total, cfg.pdf_max_pages)):
            try:
                page = doc.load_page(index)
                for uri in _extract_page_links(page):
                    key = uri.casefold().rstrip("/")
                    if key not in seen_links:
                        seen_links.add(key)
                        embedded_links.append(uri)
                text = _extract_layout_aware_text(page)
                if len(re.sub(r"\s", "", text)) >= cfg.min_chars_per_page:
                    pages_text.append(text)
                    native += 1
                    continue
                if not cfg.ocr_enabled:
                    warnings.append(f"Page {index + 1} has little text and OCR is disabled.")
                    pages_text.append(text)
                    continue
                png = page.get_pixmap(dpi=cfg.pdf_render_dpi).tobytes("png")
            except PipelineError:
                raise
            except Exception:
                raise PipelineError(FailureCode.CORRUPT_FILE) from None
            result = ocr(png)  # may raise PipelineError
            pages_text.append(result.text.strip() or text)
            ocr_pages += 1
            if result.confidence is not None:
                confs.append(result.confidence)

    full_text = "\n\n".join(p for p in pages_text if p)
    # Append embedded hyperlink URLs not already literally printed in page text so the LLM
    # and anti-fabrication grounder can recover clickable GitHub/LinkedIn/portfolio/project links.
    full_lower = full_text.casefold()
    missing_links = [
        uri
        for uri in embedded_links
        if re.sub(r"^https?://(www\.)?", "", uri.casefold()).rstrip("/") not in full_lower
    ]
    if missing_links:
        link_block = "[Embedded Links]\n" + "\n".join(missing_links[:25])
        full_text = f"{full_text}\n\n{link_block}" if full_text else link_block

    method = "pdf_text" if not ocr_pages else ("pdf_ocr" if not native else "pdf_mixed")
    return ParsedDocument(
        text=full_text,
        method=method,
        page_count=total,
        ocr_used=ocr_pages > 0,
        ocr_confidence=(sum(confs) / len(confs)) if confs else None,
        warnings=warnings,
    )
