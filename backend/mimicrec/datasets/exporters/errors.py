"""Custom exceptions raised by the exporter pipeline."""
from __future__ import annotations


class DestinationExistsError(Exception):
    """Raised when the export destination already exists and force=False."""


class DisallowedFormatError(Exception):
    """Raised when an export channel does not support the requested format."""
