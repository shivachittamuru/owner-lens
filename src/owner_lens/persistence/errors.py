"""Persistence-layer error hierarchy for OwnerLens.

These errors are deliberately distinct from the financial-domain errors
(``SecError``, ``ConceptNotFoundError``, and the insufficient-data semantics of
the analysis layers). A database failure must never be reported as, or confused
with, a financial-data failure.
"""

from __future__ import annotations

__all__ = [
    "MissingProvenanceError",
    "PersistenceError",
    "SchemaVersionError",
    "StorageConnectionError",
    "StorageReadError",
    "StorageWriteError",
]


class PersistenceError(Exception):
    """Base class for every OwnerLens persistence failure."""


class StorageConnectionError(PersistenceError):
    """Raised when the store cannot be opened, created, or set up."""


class SchemaVersionError(PersistenceError):
    """Raised when a stored schema version is incompatible with this code."""


class StorageWriteError(PersistenceError):
    """Raised when a persistence write fails."""


class StorageReadError(PersistenceError):
    """Raised when a persistence read or query fails."""


class MissingProvenanceError(PersistenceError):
    """Raised when a reported fact lacks the filing provenance the schema requires.

    The reported-fact schema stores form, filing date, and accession as required
    columns. Facts from providers that do not supply them (for example FMP) are
    not persisted until the schema deliberately supports that provenance.
    """
