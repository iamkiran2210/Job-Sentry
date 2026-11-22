import hashlib

import pytest

from app.ai_features.resumes.errors import RejectCode, UploadRejected
from app.ai_features.resumes.validation import (
    DOCX,
    JPEG,
    PDF,
    PNG,
    read_upload,
    sanitize_filename,
    validate_upload,
)

from . import fixtures as fx


def ok(name, data, cfg):
    return validate_upload(name, data, cfg)


@pytest.mark.parametrize(
    "name,data,ct",
    [
        ("cv.pdf", lambda: fx.make_pdf(), PDF),
        ("cv.DOCX", lambda: fx.make_docx(), DOCX),
        ("cv.png", lambda: fx.make_text_image(), PNG),
        ("cv.jpg", lambda: fx.make_text_image(fmt="JPEG"), JPEG),
        ("cv.jpeg", lambda: fx.make_text_image(fmt="JPEG"), JPEG),
    ],
)
def test_accepts_supported_and_hashes(name, data, ct, cfg):
    raw = data()
    v = ok(name, raw, cfg)
    assert (
            v.content_type == ct
            and v.sha256 == hashlib.sha256(raw).hexdigest()
            and v.size_bytes == len(raw)
    )


def reject(name, data, cfg, code):
    with pytest.raises(UploadRejected) as e:
        validate_upload(name, data, cfg)
    assert e.value.code == code


def test_rejects_unsupported_extension(cfg):
    reject("cv.exe", b"MZ" + b"\0" * 50, cfg, RejectCode.UNSUPPORTED_EXTENSION)
    reject("noext", fx.make_pdf(), cfg, RejectCode.UNSUPPORTED_EXTENSION)
    reject("cv.txt", b"hello world" * 10, cfg, RejectCode.UNSUPPORTED_EXTENSION)


def test_rejects_content_not_matching_extension(cfg):
    reject("cv.pdf", b"this is plain text, not a pdf", cfg, RejectCode.UNSUPPORTED_CONTENT)
    reject("cv.docx", fx.make_pdf(), cfg, RejectCode.CONTENT_TYPE_MISMATCH)
    reject("cv.png", fx.make_text_image(fmt="JPEG"), cfg, RejectCode.CONTENT_TYPE_MISMATCH)
    reject(
        "cv.pdf", b"MZ\x90\x00" + b"\0" * 100, cfg, RejectCode.UNSUPPORTED_CONTENT
    )  # exe renamed


def test_rejects_empty_and_oversize(cfg):
    reject("cv.pdf", b"", cfg, RejectCode.EMPTY_FILE)
    small = cfg.model_copy(update={"max_upload_bytes": 100})
    reject("cv.pdf", fx.make_pdf(), small, RejectCode.FILE_TOO_LARGE)


def test_rejects_macro_and_zip_bomb_docx(cfg):
    reject("cv.docx", fx.make_macro_docx(), cfg, RejectCode.UNSAFE_FILE)
    reject("cv.docx", fx.make_zip_bomb_docx(), cfg, RejectCode.UNSAFE_FILE)


def test_rejects_other_zip_and_huge_image(cfg):
    import io, zipfile

    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/workbook.xml", "<x/>")
    reject("cv.docx", b.getvalue(), cfg, RejectCode.UNSUPPORTED_CONTENT)
    tiny = cfg.model_copy(update={"max_image_pixels": 100})
    reject("cv.png", fx.make_text_image(), tiny, RejectCode.UNSAFE_FILE)


def test_filename_is_sanitized():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\x\\cv<1>.pdf") == "cv1.pdf"
    assert sanitize_filename("") == "unnamed"


@pytest.mark.asyncio
async def test_read_upload_aborts_on_size():
    class U:
        def __init__(self):
            self.n = 0

        async def read(self, size):
            self.n += 1
            return b"x" * size if self.n < 100 else b""

    with pytest.raises(UploadRejected) as e:
        await read_upload(U(), 3 * 1024 * 1024)
    assert e.value.code == RejectCode.FILE_TOO_LARGE
