"""Image preprocessing + layout-aware Tesseract OCR."""

from __future__ import annotations

import io
import os
import shutil
from typing import Callable

from ..config import ResumeSettings
from ..errors import FailureCode, PipelineError
from .types import OcrResult

OcrFn = Callable[[bytes], OcrResult]


def resolve_tesseract_cmd(configured: str | None = None) -> str:
    """Resolve the Tesseract binary path with fallback search across common locations."""
    if configured and configured.strip() and configured.strip() != "tesseract":
        candidate = os.path.expanduser(configured.strip())
        if os.path.isabs(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
        found = shutil.which(candidate)
        if found:
            return found

    found = shutil.which("tesseract")
    if found:
        return found

    candidates = [
        os.path.expanduser("~/.local/bin/tesseract"),
        "/usr/local/bin/tesseract",
        "/usr/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c

    return configured.strip() if configured and configured.strip() else "tesseract"


def preprocess_image(img):
    from PIL import Image, ImageFilter, ImageOps

    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    img = img.convert("L")
    longest = max(img.size)
    if longest < 1800:  # Tesseract works best around 300 DPI-equivalent
        scale = min(3.0, 1800 / longest)
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    elif longest > 5000:
        scale = 5000 / longest
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=1)
    # Sharpen preserves thin sans-serif resume glyph edges without blurring small text like MedianFilter(3).
    return img.filter(ImageFilter.SHARPEN)


def _order_ocr_blocks(
        blocks: list[tuple[int, float, float, float, float, list[str]]],
        page_width: float,
) -> list[list[str]]:
    """Order OCR text blocks so 2-column resumes read left column top-to-bottom, then right column."""
    if len(blocks) < 4 or page_width <= 0:
        blocks.sort(key=lambda b: (round(b[2], 1), round(b[1], 1)))
        return [b[5] for b in blocks]

    best_split: float | None = None
    best_count = 0
    for frac in (0.35, 0.42, 0.50, 0.58):
        split_x = page_width * frac
        left = [b for b in blocks if b[3] <= split_x + 12.0]
        right = [b for b in blocks if b[1] >= split_x - 12.0]
        if len(left) >= 2 and len(right) >= 2:
            left_y = (min(b[2] for b in left), max(b[4] for b in left))
            right_y = (min(b[2] for b in right), max(b[4] for b in right))
            overlap = min(left_y[1], right_y[1]) - max(left_y[0], right_y[0])
            if overlap > 50.0 and (len(left) + len(right)) > best_count:
                best_count = len(left) + len(right)
                best_split = split_x

    if best_split is None:
        blocks.sort(key=lambda b: (round(b[2], 1), round(b[1], 1)))
        return [b[5] for b in blocks]

    col_top_y = min(
        b[2] for b in blocks if b[3] <= best_split + 12.0 or b[1] >= best_split - 12.0
    )
    spanning_top, left_col, right_col, spanning_bottom = [], [], [], []
    for b in blocks:
        if b[3] <= best_split + 12.0:
            left_col.append(b)
        elif b[1] >= best_split - 12.0:
            right_col.append(b)
        elif b[2] <= col_top_y + 15.0:
            spanning_top.append(b)
        else:
            spanning_bottom.append(b)

    for grp in (spanning_top, left_col, right_col, spanning_bottom):
        grp.sort(key=lambda b: (round(b[2], 1), round(b[1], 1)))
    return [b[5] for b in (*spanning_top, *left_col, *right_col, *spanning_bottom)]


def ocr_image_bytes(data: bytes, cfg: ResumeSettings) -> OcrResult:
    from PIL import Image, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = cfg.max_image_pixels
    try:
        with Image.open(io.BytesIO(data)) as raw:
            raw.load()
            img = preprocess_image(raw)
            page_width = float(img.width)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise PipelineError(FailureCode.CORRUPT_FILE) from None

    try:
        import pytesseract
    except ImportError:
        raise PipelineError(FailureCode.OCR_UNAVAILABLE) from None

    # Tesseract is a system executable; support non-standard install paths as
    # well as the conventional PATH lookup used by the default value.
    pytesseract.pytesseract.tesseract_cmd = resolve_tesseract_cmd(cfg.tesseract_cmd)
    try:
        d = pytesseract.image_to_data(
            img,
            lang=cfg.ocr_languages,
            config="--psm 3",
            output_type=pytesseract.Output.DICT,
            timeout=cfg.ocr_timeout_seconds,
        )
    except pytesseract.TesseractNotFoundError:
        raise PipelineError(FailureCode.OCR_UNAVAILABLE) from None
    except (RuntimeError, pytesseract.TesseractError):
        raise PipelineError(FailureCode.OCR_FAILED) from None

    block_lines: dict[int, dict[tuple[int, int], list[str]]] = {}
    block_bounds: dict[int, list[float]] = {}
    confs: list[float] = []
    lefts = d.get("left") or []
    tops = d.get("top") or []
    widths = d.get("width") or []
    heights = d.get("height") or []
    for i, word in enumerate(d["text"]):
        word = word.strip()
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            continue
        if not word or conf < 0:
            continue
        bnum = int(d["block_num"][i])
        lkey = (int(d["par_num"][i]), int(d["line_num"][i]))
        block_lines.setdefault(bnum, {}).setdefault(lkey, []).append(word)
        if i < len(lefts) and i < len(tops) and i < len(widths) and i < len(heights):
            x0, y0 = float(lefts[i]), float(tops[i])
            x1, y1 = x0 + float(widths[i]), y0 + float(heights[i])
            if bnum not in block_bounds:
                block_bounds[bnum] = [x0, y0, x1, y1]
            else:
                bb = block_bounds[bnum]
                bb[0], bb[1] = min(bb[0], x0), min(bb[1], y0)
                bb[2], bb[3] = max(bb[2], x1), max(bb[3], y1)
        confs.append(conf)

    ordered_blocks_input = []
    for bnum, lines_map in block_lines.items():
        bb = block_bounds.get(bnum, [0.0, float(bnum), page_width, float(bnum) + 1.0])
        text_lines = [" ".join(words) for _, words in sorted(lines_map.items())]
        ordered_blocks_input.append((bnum, bb[0], bb[1], bb[2], bb[3], text_lines))

    ordered_groups = _order_ocr_blocks(ordered_blocks_input, page_width)
    out = ["\n".join(lines) for lines in ordered_groups if lines]
    return OcrResult("\n\n".join(out), (sum(confs) / len(confs)) if confs else None)


def default_ocr(cfg: ResumeSettings) -> OcrFn:
    return lambda data: ocr_image_bytes(data, cfg)
