"""Upload validation: size, extension AND detected content type (magic bytes), plus SHA-256."""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass

from .config import ResumeSettings
from .errors import RejectCode, UploadRejected

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
JPEG = "image/jpeg"
PNG = "image/png"

EXT_TO_TYPE = {".pdf": PDF, ".docx": DOCX, ".jpg": JPEG, ".jpeg": JPEG, ".png": PNG}
IMAGE_TYPES = {JPEG, PNG}


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    extension: str
    content_type: str
    size_bytes: int
    sha256: str


def sanitize_filename(name: str | None) -> str:
    """Display-only name. Strips paths and control chars; never used for storage paths."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*')
    return name.strip(" .")[:255] or "unnamed"


def _extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot > 0 else ""


def _docx_check(data: bytes, cfg: ResumeSettings) -> bool:
    """True if a real .docx; False if some other ZIP; raises UploadRejected if unsafe."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return False
    with zf:
        infos = zf.infolist()
        if (
                len(infos) > cfg.max_docx_entries
                or sum(i.file_size for i in infos) > cfg.max_docx_uncompressed_bytes
        ):
            raise UploadRejected(RejectCode.UNSAFE_FILE, "Document expands to an unsafe size.")
        names = {i.filename for i in infos}
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            return False
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise UploadRejected(
                RejectCode.UNSAFE_FILE, "Macro-enabled documents are not accepted."
            )
        ct = zf.getinfo("[Content_Types].xml")
        if ct.file_size <= 1_000_000 and b"macroEnabled" in zf.read(ct):
            raise UploadRejected(
                RejectCode.UNSAFE_FILE, "Macro-enabled documents are not accepted."
            )
    return True


def sniff_content_type(data: bytes, cfg: ResumeSettings) -> str | None:
    if b"%PDF-" in data[:1024]:
        return PDF
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"PK\x03\x04"):
        return DOCX if _docx_check(data, cfg) else None
    return None


def _check_image(data: bytes, cfg: ResumeSettings) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as img:  # lazy: reads header only
            w, h = img.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise UploadRejected(RejectCode.CORRUPT_FILE, "The image could not be read.") from None
    if w * h > cfg.max_image_pixels:
        raise UploadRejected(RejectCode.UNSAFE_FILE, "The image dimensions are too large.")


def validate_upload(filename: str | None, data: bytes, cfg: ResumeSettings) -> ValidatedUpload:
    safe_name = sanitize_filename(filename)
    if not data:
        raise UploadRejected(RejectCode.EMPTY_FILE, "The file is empty.")
    if len(data) > cfg.max_upload_bytes:
        raise UploadRejected(
            RejectCode.FILE_TOO_LARGE,
            f"File exceeds {cfg.max_upload_bytes // (1024 * 1024)} MB.",
        )
    ext = _extension(safe_name)
    expected = EXT_TO_TYPE.get(ext)
    if expected is None:
        raise UploadRejected(
            RejectCode.UNSUPPORTED_EXTENSION,
            "Only PDF, DOCX, JPEG and PNG files are accepted.",
        )
    detected = sniff_content_type(data, cfg)
    if detected is None:
        raise UploadRejected(
            RejectCode.UNSUPPORTED_CONTENT, "File content is not a supported format."
        )
    if detected != expected:
        raise UploadRejected(
            RejectCode.CONTENT_TYPE_MISMATCH,
            "File content does not match its extension.",
        )
    if detected in IMAGE_TYPES:
        _check_image(data, cfg)
    return ValidatedUpload(safe_name, ext, detected, len(data), hashlib.sha256(data).hexdigest())


async def read_upload(upload, max_bytes: int) -> bytes:
    """Read an UploadFile in chunks, aborting as soon as the size cap is exceeded."""
    buf = bytearray()
    while chunk := await upload.read(1024 * 1024):
        buf += chunk
        if len(buf) > max_bytes:
            raise UploadRejected(
                RejectCode.FILE_TOO_LARGE,
                f"File exceeds {max_bytes // (1024 * 1024)} MB.",
            )
    return bytes(buf)
