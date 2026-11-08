import pytest
import uuid

from app.ai_features.resumes.config import ResumeSettings
from app.ai_features.resumes.errors import StorageError, StorageObjectMissing
from app.ai_features.resumes.storage import build_key
from app.ai_features.resumes.storage.local import LocalStorage


# ------------------------------------------------------------------ storage
def test_local_storage_roundtrip_and_traversal_blocked(tmp_path):
    s = LocalStorage(tmp_path / "root")
    s.put("c/j/r/original.pdf", b"data", content_type="application/pdf")
    assert s.get("c/j/r/original.pdf") == b"data" and s.exists("c/j/r/original.pdf")
    for bad in ("../escape.txt", "/etc/passwd", "c/../../escape"):
        with pytest.raises(StorageError):
            s.put(bad, b"x", content_type="x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "root" / "symlink").symlink_to(outside, target_is_directory=True)
    with pytest.raises(StorageError):
        s.put("symlink/escape.txt", b"x", content_type="x")
    s.delete("c/j/r/original.pdf")
    s.delete("c/j/r/original.pdf")  # idempotent
    with pytest.raises(StorageObjectMissing):
        s.get("c/j/r/original.pdf")


def test_storage_key_never_contains_user_filename():
    resume_id = uuid.uuid4()
    k = build_key("C", "J", resume_id, ".pdf")
    assert k == str(resume_id)
    assert "/" not in k and ".pdf" not in k


def test_s3_backend_roundtrip():
    moto = pytest.importorskip("moto")
    import boto3
    from app.ai_features.resumes.storage.s3 import S3Storage

    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(
            Bucket="resume-test-bucket"
        )
        cfg = ResumeSettings(
            storage_backend="s3",
            s3_bucket="resume-test-bucket",
            s3_access_key_id="k",
            s3_secret_access_key="s",
            s3_server_side_encryption="AES256",
            _env_file=None,
        )
        s = S3Storage(cfg)
        s.put("c/j/r/original.pdf", b"hello", content_type="application/pdf")
        assert (
            s.exists("c/j/r/original.pdf") and s.get("c/j/r/original.pdf") == b"hello"
        )
        assert not s.exists("nope")
        with pytest.raises(StorageObjectMissing):
            s.get("nope")
        s.delete("c/j/r/original.pdf")
        assert not s.exists("c/j/r/original.pdf")
