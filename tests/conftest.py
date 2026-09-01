"""Shared fixtures: the golden corpus, and one test run per implementation."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import lz_string as lz
from lz_string import _reference

VECTORS_PATH = Path(__file__).parent / "data" / "vectors.jsonl.gz"

# Which compressed form of a vector belongs to which pair of functions. The names match the
# keys the generator writes, so a failure points straight at a field in the corpus file.
VARIANTS = (
    ("base64", "compress_to_base64", "decompress_from_base64"),
    ("uri", "compress_to_encoded_uri_component", "decompress_from_encoded_uri_component"),
    ("utf16", "compress_to_utf16", "decompress_from_utf16"),
    ("raw", "compress", "decompress"),
)


def _load() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with gzip.open(VECTORS_PATH, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    return rows[0], rows[1:]


_HEADER, _VECTORS = _load()


@pytest.fixture(scope="session")
def corpus_header() -> dict[str, Any]:
    return _HEADER


def vectors(group: str | None = None) -> list[dict[str, Any]]:
    if group is None:
        return _VECTORS
    return [row for row in _VECTORS if row["group"] == group]


def groups() -> list[str]:
    return sorted({row["group"] for row in _VECTORS})


IMPLEMENTATIONS = {"package": lz, "reference": _reference}


@pytest.fixture(params=list(IMPLEMENTATIONS))
def implementation(request: pytest.FixtureRequest) -> ModuleType:
    """Run the test twice: against the shipped extension and against the Python reference.

    The reference is not a fallback — nothing imports it at runtime. It is here so the
    suite has a second opinion that is neither the extension under test nor a call out to
    node, and so that a disagreement between them fails a test instead of reaching a user.
    """
    return IMPLEMENTATIONS[request.param]
