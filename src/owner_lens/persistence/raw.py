"""Raw SEC payload storage boundary for OwnerLens Slice 4A.

The relational store references raw Company Facts payloads by content hash rather
than embedding them. This module defines the small ``RawSnapshotStore`` protocol
and a local filesystem implementation. A future ``BlobRawSnapshotStore`` can
satisfy the same protocol in Slice 4B with no relational schema change.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol, runtime_checkable

from owner_lens.persistence.errors import StorageReadError, StorageWriteError

__all__ = [
    "FilesystemRawSnapshotStore",
    "RawSnapshotStore",
    "compute_content_hash",
]


def compute_content_hash(payload: bytes) -> str:
    """Return the SHA-256 hex digest identifying a raw payload."""
    return hashlib.sha256(payload).hexdigest()


@runtime_checkable
class RawSnapshotStore(Protocol):
    """Content-addressed store for raw source payloads."""

    def put(self, content_hash: str, payload: bytes) -> str:
        """Store the payload under its content hash and return a reference."""
        ...

    def get(self, content_hash: str) -> bytes:
        """Return the payload for a content hash or raise ``StorageReadError``."""
        ...

    def exists(self, content_hash: str) -> bool:
        """Return whether a payload is stored for the content hash."""
        ...


class FilesystemRawSnapshotStore:
    """A local filesystem ``RawSnapshotStore`` keyed by content hash."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageWriteError(
                f"Cannot create raw snapshot root {self._root}: {exc}"
            ) from exc

    def _path(self, content_hash: str) -> Path:
        return self._root / f"{content_hash}.json"

    def put(self, content_hash: str, payload: bytes) -> str:
        path = self._path(content_hash)
        try:
            if not path.exists():
                path.write_bytes(payload)
        except OSError as exc:
            raise StorageWriteError(
                f"Cannot write raw snapshot {content_hash}: {exc}"
            ) from exc
        return str(path)

    def get(self, content_hash: str) -> bytes:
        path = self._path(content_hash)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise StorageReadError(
                f"Cannot read raw snapshot {content_hash}: {exc}"
            ) from exc

    def exists(self, content_hash: str) -> bool:
        return self._path(content_hash).exists()
