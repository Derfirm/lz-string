"""Round-trips over generated input, including the cases that break naive ports.

The corpus in test_golden.py proves we agree with JavaScript on inputs someone thought to
write down. This file generates inputs nobody wrote down: random code units, surrogate
halves in the wrong order, astral characters glued to their halves. It is seeded, so a
failure reproduces; ``LZSTRING_SEED`` changes the draw when you want a fresh sweep.

Characters above U+FFFF are written with chr() rather than as literals throughout: what
each case is about is which UTF-16 code units it is made of, and an escape or a pasted
emoji hides exactly that.
"""

from __future__ import annotations

import json
import os
import random

import pytest

from lz_string._reference import _from_units as as_code_points
from tests.conftest import VARIANTS

SEED = int(os.environ.get("LZSTRING_SEED", "20260901"))

GRINNING = chr(0x1F600)  # one Python character
HIGH, LOW = chr(0xD83D), chr(0xDE00)  # ... and the two UTF-16 units JavaScript sees


def _pairs(implementation):
    return [(getattr(implementation, c), getattr(implementation, d)) for _, c, d in VARIANTS]


@pytest.mark.parametrize("length", [1, 2, 3, 7, 64, 1000, 40000])
def test_random_code_units(implementation, length: int) -> None:
    """Any sequence of UTF-16 code units must survive, meaningful or not."""
    rng = random.Random(SEED + length)
    # Surrogates are drawn as often as anything else: for lz-string they are ordinary
    # units, and the whole API is built in code units so that stays true here.
    text = "".join(chr(rng.randrange(0x0000, 0x10000)) for _ in range(length))
    # Compared against the normalised form, not the draw: two adjacent halves that happen
    # to form a valid pair are one character to JavaScript, and come back as one here.
    # Nothing is lost — as_code_points(text) has the same UTF-16 units as text.
    for compress, decompress in _pairs(implementation):
        assert decompress(compress(text)) == as_code_points(text)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(HIGH + LOW, id="pair-written-as-halves"),
        pytest.param(GRINNING, id="astral-character"),
        pytest.param(chr(0xD800), id="lone-high"),
        pytest.param(chr(0xDFFF), id="lone-low"),
        pytest.param(chr(0xDC00) + chr(0xD800), id="pair-in-reverse-order"),
        pytest.param("a" + chr(0xD805) + "b", id="lone-surrogate-in-text"),
        pytest.param('{"journal":"' + chr(0xD805) + '"}', id="the-degrees-of-lewdity-shape"),
    ],
)
def test_surrogates_survive(implementation, text: str) -> None:
    for compress, decompress in _pairs(implementation):
        assert decompress(compress(text)) == as_code_points(text)


def test_a_pair_of_halves_comes_back_as_the_character(implementation) -> None:
    """The one place where in != out, and why that is right rather than lossy.

    A Python string can hold U+D83D and U+DE00 as two separate code points; a JavaScript
    string cannot tell that apart from the single character they encode, and the format is
    defined in JavaScript's terms. So the round-trip normalises: the units are preserved
    exactly, their grouping into code points is not. Callers that must keep the halves
    apart are really asking for bytes, and should hold UTF-16 bytes themselves.
    """
    assert implementation.decompress_from_base64(implementation.compress_to_base64(HIGH + LOW)) == GRINNING
    assert as_code_points(HIGH + LOW) == GRINNING
    # A half with nothing to pair with is untouched — this is the Degrees of Lewdity case.
    assert implementation.decompress_from_base64(implementation.compress_to_base64(HIGH + "x")) == HIGH + "x"


def test_an_astral_character_is_two_units_not_one_value(implementation) -> None:
    """The bug that makes the PyPI ``lzstring`` package corrupt saves.

    U+1F600 is one Python character whose ordinal does not fit in the 16-bit field the
    format has for a new character. Ported naively it is written truncated and the game
    reads U+F600 — a private-use box where the player's emoji was. Here the character and
    its two halves must compress to the same bytes, which is what "code units, not code
    points" means in practice.
    """
    assert implementation.compress_to_base64(GRINNING) == implementation.compress_to_base64(HIGH + LOW)
    assert implementation.decompress_from_base64(implementation.compress_to_base64(GRINNING)) == GRINNING

    save = '{"name":"Marie ' + GRINNING + '"}'
    restored = implementation.decompress_from_base64(implementation.compress_to_base64(save))
    assert restored == save
    assert chr(0xF600) not in (restored or "")  # the truncated value the broken port writes


@pytest.mark.parametrize("depth", [1, 5, 50])
def test_save_shaped_json(implementation, depth: int) -> None:
    rng = random.Random(SEED + depth)
    payload = json.dumps(
        {
            "system": {"@": "Game_System", "_saveCount": rng.randrange(1000)},
            "party": {
                "_gold": rng.randrange(10**7),
                "_items": {str(i): rng.randrange(99) for i in range(depth * 10)},
            },
            "text": ("Привет " + GRINNING + " ") * depth,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert implementation.decompress_from_base64(implementation.compress_to_base64(payload)) == payload


def test_compression_actually_compresses(implementation) -> None:
    # A guard against a "round-trip" that is really a very slow base64: the dictionary has
    # to be doing its job on repetitive input.
    text = '{"switches":[true,false,true,false]},' * 500
    assert len(implementation.compress_to_base64(text)) < len(text) / 10


@pytest.mark.parametrize("size", [10_000, 200_000])
def test_dictionary_growth_past_the_numbits_steps(implementation, size: int) -> None:
    # Long, low-repetition input walks numBits from 3 upwards; an off-by-one in the
    # enlargeIn bookkeeping only shows up after those steps.
    rng = random.Random(SEED + size)
    text = "".join(rng.choice('abcdefghij0123456789{}[]:,"') for _ in range(size))
    assert implementation.decompress_from_base64(implementation.compress_to_base64(text)) == text
