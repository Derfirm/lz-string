"""The corpus tests: every function, against output produced by the JavaScript original.

The oracle is `lz-string` on npm, not another Python package, because the files this code
reads are written by games running that library. Regenerate the corpus with
``node tools/gen_vectors.mjs`` — it is deterministic, so a regenerated file that differs
means the reference changed, which is itself worth seeing in a diff.
"""

from __future__ import annotations

import pytest

import lz_string as lz
from tests.conftest import VARIANTS, groups, vectors


def _fail(kind: str, row: dict, expected: str, got: str) -> str:
    return (
        f"vector #{row['id']} ({row['group']}, {len(row['input'])} chars) {kind}\n"
        f"  expected ...{expected[-60:]!r}\n"
        f"  got      ...{got[-60:]!r}"
    )


@pytest.mark.parametrize("group", groups())
@pytest.mark.parametrize("variant", [v[0] for v in VARIANTS])
def test_compress_matches_the_reference(implementation, group: str, variant: str) -> None:
    compress = getattr(implementation, dict((v[0], v[1]) for v in VARIANTS)[variant])
    for row in vectors(group):
        got = compress(row["input"])
        assert got == row[variant], _fail(f"{variant} compress via {implementation.__name__}", row, row[variant], got)


@pytest.mark.parametrize("group", groups())
@pytest.mark.parametrize("variant", [v[0] for v in VARIANTS])
def test_decompress_matches_the_reference(implementation, group: str, variant: str) -> None:
    decompress = getattr(implementation, dict((v[0], v[2]) for v in VARIANTS)[variant])
    for row in vectors(group):
        got = decompress(row[variant])
        assert got == row["input"], _fail(f"{variant} decompress via {implementation.__name__}", row, row["input"], got or "")


def test_corpus_is_the_one_we_think_it_is(corpus_header: dict) -> None:
    # A corpus regenerated against a different lz-string release is a different oracle;
    # pin it so an upgrade is a deliberate, reviewable change rather than a silent one.
    assert corpus_header["generator"] == "lz-string"
    assert corpus_header["version"] == "1.5.0"
    assert corpus_header["count"] == len(vectors())


def test_corpus_covers_what_it_claims_to() -> None:
    """Guard against a generator edit that quietly drops a category."""
    covered = {row["group"] for row in vectors()}
    assert covered >= {
        "codeunit-sweep",  # all 65536 code units, surrogates included
        "lone-surrogate",  # what a Degrees of Lewdity journal is made of
        "unicode",         # astral characters: one Python char, two JavaScript ones
        "save-shaped",     # the shape our own uploads arrive in
        "large",           # dictionary growth past the numBits steps
    }
    assert any(len(row["input"]) > 100_000 for row in vectors()), "no large vector left"
    surrogates = [row for row in vectors("lone-surrogate")]
    assert all(any(0xD800 <= ord(c) <= 0xDFFF for c in row["input"]) for row in surrogates)
