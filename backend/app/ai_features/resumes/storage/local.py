from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..errors import StorageError, StorageObjectMissing
from .base import ObjectStorage


class LocalStorage(ObjectStorage):
    backend_name = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:  # blocks ../ traversal and absolute keys
            raise StorageError("invalid key")
        return p

    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        p = self._path(key)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)  # atomic
        except OSError as exc:
            raise StorageError("write failed") from exc

    def get(self, key: str) -> bytes:
        p = self._path(key)
        try:
            return p.read_bytes()
        except FileNotFoundError as exc:
            raise StorageObjectMissing("missing") from exc
        except OSError as exc:
            raise StorageError("read failed") from exc

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError("delete failed") from exc

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()
