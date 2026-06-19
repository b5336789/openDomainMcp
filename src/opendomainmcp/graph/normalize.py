"""Deterministic name normalization for graph entities."""

from __future__ import annotations


def normalize_name(name: str) -> str:
    """Lowercase, trim, and collapse internal whitespace.

    The normalized form is the dedup/lookup key; the first-seen original is
    kept as the display name.
    """
    return " ".join(str(name).lower().split())
