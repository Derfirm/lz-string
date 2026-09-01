"""The shipped extension against the Python reference, where it is hardest to be right.

The corpus proves both agree with JavaScript on well-formed payloads. This file is about
the other half: damaged input, where the crate underneath the extension does not agree with
the reference on its own and had to be corrected (SPEC.md §7). Those corrections live in
Rust, so nothing here can paper over them from Python.
"""

from __future__ import annotations

import random

import pytest

import lz_string as lz
from lz_string import _reference
from tests.conftest import VARIANTS, vectors


def test_the_package_really_is_the_extension() -> None:
    """No silent fallback: the shipped functions must be the compiled ones.

    If the extension is ever made optional again by accident, this is the test that says so
    — the package would still work, only 15x slower and with a different set of bugs.
    """
    from lz_string import _native

    assert _native.compress_to_base64("x".encode("utf-16-le")) == lz.compress_to_base64("x")


@pytest.mark.parametrize("variant,compress_name,decompress_name", VARIANTS)
def test_identical_bytes_on_real_shapes(variant: str, compress_name: str, decompress_name: str) -> None:
    rng = random.Random(20260901)
    for row in rng.sample(vectors(), 120):
        text = row["input"]
        packed = getattr(lz, compress_name)(text)
        assert packed == getattr(_reference, compress_name)(text), f"{variant}: compressed differently"
        # And each must read what the other wrote.
        assert getattr(lz, decompress_name)(packed) == text
        assert getattr(_reference, decompress_name)(packed) == text


def test_base64_padding_follows_the_reference() -> None:
    """lz-str pads base64 with one "=" too many; the extension re-pads.

    Kept as its own test because it is a divergence in a third-party crate: if a future
    version fixes it, this fails loudly rather than leaving a silent double correction.
    """
    for text in ["", "a", "ab", "abc", "gold" * 10, "x" * 1000]:
        packed = lz.compress_to_base64(text)
        assert packed == _reference.compress_to_base64(text)
        assert len(packed) % 4 == 0


def _malformed(count: int = 400) -> list[str]:
    """Payloads damaged the ways real ones are: truncated, mutated, polluted."""
    rng = random.Random(4242)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
    good = lz.compress_to_base64('{"party":{"_gold":8536},"switches":[true,false]}' * 20)
    out = []
    for _ in range(count):
        kind = rng.randrange(6)
        if kind == 0:
            out.append("".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 200))))
        elif kind == 1:  # one character swapped
            i = rng.randrange(len(good))
            out.append(good[:i] + rng.choice(alphabet) + good[i + 1 :])
        elif kind == 2:  # cut short
            out.append(good[: rng.randrange(len(good))])
        elif kind == 3:  # something that is not in the alphabet at all
            i = rng.randrange(len(good))
            out.append(good[:i] + rng.choice("!@# \n\t") + good[i:])
        elif kind == 4:  # not a payload in any encoding
            out.append("".join(chr(rng.randrange(0x10000)) for _ in range(rng.randrange(0, 80))))
        else:  # trailing rubbish after a good payload
            out.append(good + "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 50))))
    return out


@pytest.mark.parametrize("function", [v[2] for v in VARIANTS])
def test_damaged_input_decodes_the_same_either_way(function: str) -> None:
    """This is what pins the corrections in rust/src/lib.rs.

    It also asserts that nothing raises — a pyo3 panic is not an ``Exception`` and would slip
    past an ordinary except clause straight to the caller.
    """
    for payload in _malformed():
        answers = {}
        for name, module in (("package", lz), ("reference", _reference)):
            try:
                answers[name] = getattr(module, function)(payload)
            except BaseException as error:  # noqa: BLE001 - a panic is the point
                pytest.fail(f"{function} raised {type(error).__name__} in {name}: {payload[:40]!r}")
        assert answers["package"] == answers["reference"], (
            f"{function} disagrees on {payload[:40]!r}: "
            f"package={answers['package']!r:.40}, reference={answers['reference']!r:.40}"
        )


def test_a_trimmed_padding_character_still_reads() -> None:
    """The crate refuses this; the extension retries with the character put back.

    Realistic because the last character carries no data: anything that strips trailing
    whitespace or truncates by one byte produces exactly this file.
    """
    payload = lz.compress_to_base64('{"a":1,"b":[1,2,3],"c":"hello world"}')
    trimmed = payload.rstrip("=")[:-1]
    assert lz.decompress_from_base64(trimmed) == lz.decompress_from_base64(payload)


def test_characters_outside_the_alphabet_read_as_zero_bits() -> None:
    """The other correction: they must not be skipped, they must occupy their place.

    A payload whose padding was replaced by junk decodes to the same thing, because both
    read as zeros; a payload with junk spliced into the middle does not, because the zeros
    are in the stream rather than instead of it.
    """
    payload = lz.compress_to_base64('{"a":1,"b":[1,2,3],"c":"hello world"}')
    body = payload.rstrip("=")
    junked = body + "!" * (len(payload) - len(body))
    assert lz.decompress_from_base64(junked) == lz.decompress_from_base64(payload)
    assert lz.decompress_from_base64(junked) == _reference.decompress_from_base64(junked)
