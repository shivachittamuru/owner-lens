"""Raw SEC payload storage boundary for OwnerLens Slice 4A.

The relational store references raw Company Facts payloads by content hash rather
than embedding them. This module defines the small ``RawSnapshotStore`` protocol
and a local filesystem implementation. A future ``BlobRawSnapshotStore`` can
satisfy the same protocol in Slice 4B with no relational schema change.
"""

from __future__ import annotations

import hashlib
import json
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


# Snapshots whose CIK cannot be derived from the payload are grouped here.
_UNSCOPED = "_unscoped"


def _cik_from_payload(payload: bytes) -> str | None:
    """Return the zero-padded 10-digit CIK carried by a Company Facts payload."""
    try:
        obj = json.loads(payload)
    except (ValueError, TypeError):
        return None
    cik = obj.get("cik") if isinstance(obj, dict) else None
    if isinstance(cik, bool) or not isinstance(cik, (int, str)):
        return None
    digits = str(cik).strip()
    return digits.zfill(10) if digits.isdigit() else None


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
    """A local filesystem ``RawSnapshotStore`` addressed by content hash.

    Payloads are laid out as ``<root>/<CIK>/<content-hash>.json``: the content
    hash is the identity and the CIK (derived from the payload, never the mutable
    ticker) groups a company's snapshots. ``get``/``exists`` resolve by content
    hash alone via a cache and a filename fallback, so they work in a fresh
    process without the payload in hand.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageWriteError(
                f"Cannot create raw snapshot root {self._root}: {exc}"
            ) from exc
        self._by_hash: dict[str, Path] = {}

    def put(self, content_hash: str, payload: bytes) -> str:
        prefix = _cik_from_payload(payload) or _UNSCOPED
        path = self._root / prefix / f"{content_hash}.json"
        try:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
        except OSError as exc:
            raise StorageWriteError(
                f"Cannot write raw snapshot {content_hash}: {exc}"
            ) from exc
        self._by_hash[content_hash] = path
        return str(path)

    def _resolve(self, content_hash: str) -> Path | None:
        cached = self._by_hash.get(content_hash)
        if cached is not None:
            return cached
        found = next(self._root.rglob(f"{content_hash}.json"), None)
        if found is not None:
            self._by_hash[content_hash] = found
        return found

    def get(self, content_hash: str) -> bytes:
        path = self._resolve(content_hash)
        if path is None:
            raise StorageReadError(f"Raw snapshot {content_hash} not found.")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise StorageReadError(
                f"Cannot read raw snapshot {content_hash}: {exc}"
            ) from exc

    def exists(self, content_hash: str) -> bool:
        return self._resolve(content_hash) is not None
