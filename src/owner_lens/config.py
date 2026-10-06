"""Local-first configuration boundary for OwnerLens.

Ordinary environment variables are the configuration contract; a local ``.env``
file is loaded only as a developer convenience. Settings resolve into one
immutable object, and ``build_local_store`` composes the Slice 4A local backends
(``SqliteStore`` over a ``FilesystemRawSnapshotStore``) from them. This module is
composition-level; no financial module imports it, and it introduces no cloud
configuration. The optional FMP API key (Slice 5B) is read here and is required
only when a caller explicitly requests FMP via ``require_fmp_api_key``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

from owner_lens.fmp import FmpConfigurationError
from owner_lens.persistence import FilesystemRawSnapshotStore, SqliteStore

__all__ = [
    "FMP_API_KEY_ENV",
    "OwnerLensSettings",
    "build_local_store",
    "load_settings",
    "require_fmp_api_key",
]

FMP_API_KEY_ENV: Final = "OWNER_LENS_FMP_API_KEY"
_DEFAULT_DB_PATH: Final = "data/ownerlens.db"
_DEFAULT_RAW_DATA_PATH: Final = "data/raw/sec/company_facts"


@dataclass(frozen=True)
class OwnerLensSettings:
    """Immutable OwnerLens local runtime configuration.

    ``fmp_api_key`` is a secret: it is never logged or included in error text.
    """

    sec_user_agent: str | None
    db_path: str
    raw_data_path: str
    fmp_api_key: str | None = field(default=None, repr=False)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def load_settings(*, env_file: str | None = ".env") -> OwnerLensSettings:
    """Resolve settings from the environment, loading ``.env`` for convenience.

    Environment variables already present take precedence over ``.env`` values.
    """
    if env_file is not None:
        load_dotenv(env_file, override=False)
    return OwnerLensSettings(
        sec_user_agent=_clean(os.environ.get("OWNER_LENS_SEC_USER_AGENT")),
        db_path=_clean(os.environ.get("OWNER_LENS_DB_PATH")) or _DEFAULT_DB_PATH,
        raw_data_path=_clean(os.environ.get("OWNER_LENS_RAW_DATA_PATH"))
        or _DEFAULT_RAW_DATA_PATH,
        fmp_api_key=_clean(os.environ.get(FMP_API_KEY_ENV)),
    )


def require_fmp_api_key(settings: OwnerLensSettings) -> str:
    """Return the configured FMP API key or raise a clear configuration error."""
    if settings.fmp_api_key is None:
        raise FmpConfigurationError(
            f"FMP was requested but {FMP_API_KEY_ENV} is not set. Add it to the "
            "environment or the local .env file (see .env.example)."
        )
    return settings.fmp_api_key


def build_local_store(settings: OwnerLensSettings) -> SqliteStore:
    """Compose the local SQLite + filesystem persistence from settings.

    Ensures the SQLite parent directory exists; the raw store creates its own
    root. The caller invokes ``initialize()`` before use.
    """
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_store = FilesystemRawSnapshotStore(Path(settings.raw_data_path))
    return SqliteStore(db_path, raw_store=raw_store)
