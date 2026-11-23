"""Image preprocessing + layout-aware Tesseract OCR with optional multimodal vision assist."""

from __future__ import annotations

import asyncio
import concurrent.futures
import io
import logging
import os
import re
import shutil
from typing import Callable

from ..config import ResumeSettings
from ..errors import FailureCode, PipelineError
from .types import OcrResult

OcrFn = Callable[[bytes], OcrResult]
log = logging.getLogger("resumes.ocr")

_VISION_CONF_THRESHOLD = 88.0
_SUSPICIOUS_OCR_EMAIL_RE = re.compile(
    r"\b[a-z0-9._%+-]+\s+[a-z0-9._%+-]*[s5©®0](?:gmail|yahoo|outlook|hotmail|icloud|protonmail)\.[a-z]{2,}\b",
    re.I,
)
_VISION_OCR_INSTRUCTIONS = (
    "You are a high-precision OCR transcription engine for resumes. "
    "Transcribe EVERY visible word from the resume image verbatim into clean plain text. "
    "Rules:\n"
    "1. Preserve logical reading order: top full-width header first, then left column completely top-to-bottom, "
    "then right column completely top-to-bottom (never interleave two columns on the same line).\n"
    "2. Transcribe names, email addresses (pay careful attention to '@' and dots), phone numbers, URLs, "
    "dates, degrees, institutions, skills, and bullet points with exact spelling.\n"
    "3. Ignore decorative icons, progress bars, stars, or graphics; do not describe images or add commentary.\n"
    "4. Output ONLY the transcribed resume text, with zero markdown fences or explanations. "
    "Never invent any text not visible in the image."
)


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
    if longest < 2400:  # Tesseract works best around 300+ DPI-equivalent
        scale = min(3.5, 2400 / longest)
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    elif longest > 5000:
        scale = 5000 / longest
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=1)
    # Gentle UnsharpMask crispens thin sans-serif glyphs without JPEG ringing halos from SHARPEN.
    return img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=120, threshold=3))


def _order_ocr_blocks(
        blocks: list[tuple[int, float, float, float, float, list[str]]],
        page_width: float,
) -> list[list[str]]:
    """Order OCR text blocks so 2-column resumes read left column top-to-bottom, then right column."""
    if len(blocks) < 4 or page_width <= 0:
        blocks.sort(key=lambda b: (round(b[2], 1), round(b[1], 1)))
        return [b[5] for b in blocks]

    best_split: float | None = None
    best_score = -1
    for frac in (0.28, 0.32, 0.36, 0.40, 0.45, 0.50, 0.55, 0.60, 0.64, 0.68, 0.72):
        split_x = page_width * frac
        left = [b for b in blocks if b[3] <= split_x + 12.0]
        right = [b for b in blocks if b[1] >= split_x - 12.0]
        if len(left) >= 2 and len(right) >= 2:
            left_y = (min(b[2] for b in left), max(b[4] for b in left))
            right_y = (min(b[2] for b in right), max(b[4] for b in right))
            band_top = max(left_y[0], right_y[0])
            band_bot = min(left_y[1], right_y[1])
            overlap = band_bot - band_top
            if overlap <= 50.0:
                continue
            straddling = [
                b
                for b in blocks
                if b[1] < split_x - 12.0
                and b[3] > split_x + 12.0
                and b[4] > band_top
                and b[2] < band_bot
            ]
            score = (len(left) + len(right)) * 2 - len(straddling) * 3
            if score > best_score:
                best_score = score
                best_split = split_x

    if best_split is None:
        blocks.sort(key=lambda b: (round(b[2], 1), round(b[1], 1)))
        return [b[5] for b in blocks]

    paired_left = [b for b in blocks if b[3] <= best_split + 12.0]
    paired_right = [b for b in blocks if b[1] >= best_split - 12.0]
    col_top_y = max(min(b[2] for b in paired_left), min(b[2] for b in paired_right))
    col_bot_y = min(max(b[4] for b in paired_left), max(b[4] for b in paired_right))

    spanning_top, left_col, right_col, spanning_bottom = [], [], [], []
    for b in blocks:
        if b[3] <= best_split + 12.0:
            left_col.append(b)
        elif b[1] >= best_split - 12.0:
            right_col.append(b)
        elif b[4] <= col_top_y + 15.0:
            spanning_top.append(b)
        elif b[2] >= col_bot_y - 15.0:
            spanning_bottom.append(b)
        else:
            mid_x = (b[1] + b[3]) / 2.0
            if mid_x <= best_split or b[1] < page_width * 0.18:
                left_col.append(b)
            else:
                right_col.append(b)

    for grp in (spanning_top, left_col, right_col, spanning_bottom):
        grp.sort(key=lambda b: (round(b[2], 1), round(b[1], 1)))
    return [b[5] for b in (*spanning_top, *left_col, *right_col, *spanning_bottom)]


def _split_line_segments(
        words: list[tuple[float, float, float, float, str]],
        page_width: float,
) -> list[tuple[float, float, float, float, str]]:
    """Split a Tesseract line into separate horizontal segments when a wide column gutter exists."""
    if not words:
        return []
    words.sort(key=lambda w: w[0])
    heights = [max(4.0, w[3] - w[1]) for w in words]
    avg_h = sum(heights) / len(heights)
    gap_threshold = max(3.5 * avg_h, page_width * 0.055)

    segments: list[list[tuple[float, float, float, float, str]]] = [[words[0]]]
    for w in words[1:]:
        prev = segments[-1][-1]
        gap = w[0] - prev[2]
        if gap > gap_threshold:
            segments.append([w])
        else:
            segments[-1].append(w)

    out: list[tuple[float, float, float, float, str]] = []
    for seg in segments:
        x0 = min(w[0] for w in seg)
        y0 = min(w[1] for w in seg)
        x1 = max(w[2] for w in seg)
        y1 = max(w[3] for w in seg)
        out.append((x0, y0, x1, y1, " ".join(w[4] for w in seg)))
    return out


def _detect_media_type(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return "image/png"


async def _vision_transcribe_async(data: bytes) -> str | None:
    from pydantic_ai import Agent, BinaryContent

    from app.ai_features.ai.models import build_model, model_settings
    from app.ai_features.ai.settings import get_ai_settings

    ai_settings = get_ai_settings()
    if ai_settings.offline:
        return None
    chain = ai_settings.model_chain_for_tier("fast")
    if not chain or not any(
        m.startswith(("openai:", "openai-chat:", "google:", "google-gla:", "anthropic:"))
        for m in chain
    ):
        return None

    media_type = _detect_media_type(data)
    payload = data
    # Keep vision upload compact (<2200px longest side) for fast latency and crisp glyph clarity
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as raw:
            img = ImageOps.exif_transpose(raw)
            if max(img.size) > 2200:
                scale = 2200 / max(img.size)
                img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG", optimize=True)
                payload = buf.getvalue()
                media_type = "image/png"
    except Exception:
        pass

    model = build_model(ai_settings, "resume_profile", model_chain=chain)
    agent = Agent(
        model,
        output_type=str,
        instructions=_VISION_OCR_INSTRUCTIONS,
        model_settings=model_settings(
            ai_settings,
            thinking_budget=0,
            max_tokens=4096,
            reasoning_effort="none",
            primary_model=chain[0],
        ),
        name="jobsentry-vision-ocr",
    )
    result = await asyncio.wait_for(
        agent.run(
            [
                "Transcribe this resume image verbatim in clean reading order.",
                BinaryContent(data=payload, media_type=media_type),
            ]
        ),
        timeout=30.0,
    )
    text = str(result.output or "").strip()
    # Strip accidental markdown code fences if a model wrapped output
    if text.startswith("```") and text.endswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    return text if len(re.sub(r"\s", "", text)) >= 40 else None


def _try_vision_ocr(data: bytes) -> str | None:
    try:
        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(_vision_transcribe_async(data))).result(
                    timeout=35.0
                )
        except RuntimeError:
            return asyncio.run(_vision_transcribe_async(data))
    except Exception as exc:  # noqa: BLE001
        log.info("Vision OCR assist skipped/failed (%s); keeping Tesseract output", type(exc).__name__)
        return None


def _needs_vision_assist(text: str, confidence: float | None) -> bool:
    if confidence is None or confidence < _VISION_CONF_THRESHOLD:
        return True
    if _SUSPICIOUS_OCR_EMAIL_RE.search(text):
        return True
    # Detect OCR kerning splits on capitalized words (e.g. "J ohn Doe")
    if re.search(r"\b[A-Z]\s+[a-z]{2,}\b", text[:400]):
        return True
    return False


def ocr_image_bytes(
        data: bytes,
        cfg: ResumeSettings,
        *,
        allow_vision_assist: bool = False,
) -> OcrResult:
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

    raw_lines: dict[tuple[int, int, int], list[tuple[float, float, float, float, str]]] = {}
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
        lkey = (bnum, int(d["par_num"][i]), int(d["line_num"][i]))
        if i < len(lefts) and i < len(tops) and i < len(widths) and i < len(heights):
            x0, y0 = float(lefts[i]), float(tops[i])
            x1, y1 = x0 + float(widths[i]), y0 + float(heights[i])
        else:
            x0, y0, x1, y1 = 0.0, float(bnum), page_width, float(bnum) + 12.0
        raw_lines.setdefault(lkey, []).append((x0, y0, x1, y1, word))
        confs.append(conf)

    # Split lines across wide horizontal gutters so 2-column image resumes never interleave columns.
    ordered_blocks_input: list[tuple[int, float, float, float, float, list[str]]] = []
    block_groups: dict[tuple[int, int], list[tuple[float, float, float, float, str]]] = {}
    for (bnum, _pnum, _lnum), words in sorted(raw_lines.items()):
        segs = _split_line_segments(words, page_width)
        for seg_idx, seg in enumerate(segs):
            # If a single Tesseract block had multiple horizontal segments, separate them by column bucket
            col_bucket = 0 if len(segs) == 1 else (1 if (seg[0] + seg[2]) / 2.0 > page_width * 0.45 else 0)
            key = (bnum, col_bucket if len(segs) > 1 else seg_idx)
            block_groups.setdefault(key, []).append(seg)

    seq_id = 0
    for _key, segs in block_groups.items():
        segs.sort(key=lambda s: (round(s[1], 1), round(s[0], 1)))
        x0 = min(s[0] for s in segs)
        y0 = min(s[1] for s in segs)
        x1 = max(s[2] for s in segs)
        y1 = max(s[3] for s in segs)
        ordered_blocks_input.append((seq_id, x0, y0, x1, y1, [s[4] for s in segs]))
        seq_id += 1

    ordered_groups = _order_ocr_blocks(ordered_blocks_input, page_width)
    out = ["\n".join(lines) for lines in ordered_groups if lines]
    tess_text = "\n\n".join(out)
    mean_conf = (sum(confs) / len(confs)) if confs else None

    if allow_vision_assist and _needs_vision_assist(tess_text, mean_conf):
        vision_text = _try_vision_ocr(data)
        if vision_text:
            return OcrResult(vision_text, 96.0)

    return OcrResult(tess_text, mean_conf)


def default_ocr(cfg: ResumeSettings) -> OcrFn:
    return lambda data: ocr_image_bytes(data, cfg, allow_vision_assist=True)
