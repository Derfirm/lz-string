"""What the functions do with input that is not a payload.

Every expectation here was read off the JavaScript reference (lz-string 1.5.0, node 25)
rather than decided by us — the point of the package is that a caller can swap it in for
the real thing and see no change. The one deliberate departure is documented below and in
SPEC.md: where the reference throws, this package returns an empty string.
"""

from __future__ import annotations

import pytest

import lz_string as lz


@pytest.fixture
def payload(implementation) -> str:
    return implementation.compress_to_base64('{"a":1,"b":[1,2,3],"c":"hello world"}')


def test_none_in_empty_out(implementation) -> None:
    # The reference treats null as "nothing to do" in both directions.
    assert implementation.compress_to_base64(None) == ""
    assert implementation.compress(None) == ""
    assert implementation.decompress_from_base64(None) == ""


def test_empty_string_decompresses_to_none(implementation) -> None:
    # Not a typo and not symmetric with the above: decompressFromBase64("") is null in JS.
    assert implementation.decompress_from_base64("") is None
    assert implementation.decompress("") is None
    assert implementation.decompress_from_utf16("") is None


def test_empty_string_compresses_to_a_real_payload(implementation) -> None:
    # An empty save still produces bytes — the end marker — and reads back as empty.
    assert implementation.compress_to_base64("") == "Q==="
    assert implementation.decompress_from_base64("Q===") == ""


@pytest.mark.parametrize(
    "junk",
    [
        pytest.param("!!!", id="outside-the-alphabet"),
        pytest.param("====", id="padding-only"),
        pytest.param("A", id="single-character"),
    ],
)
def test_junk_that_runs_out_of_bits_is_empty(implementation, junk: str) -> None:
    # "the stream ended before the end marker" — the reference answers "" for each of these.
    assert implementation.decompress_from_base64(junk) == ""


@pytest.mark.parametrize(
    "junk",
    [
        pytest.param("+", id="impossible-header"),
        pytest.param("zzzz", id="valid-alphabet-nonsense"),
        pytest.param("N4Ig" + "zzzz", id="valid-prefix-then-nonsense"),
    ],
)
def test_junk_that_is_not_a_payload_is_none(implementation, junk: str) -> None:
    """The other failure: a token that no encoder could have written.

    The reference answers null for most of this class and throws a TypeError for some of it
    — it is running on a JavaScript `undefined` by then, and over 4000 malformed payloads
    that came out as null 67%, "" 15%, TypeError 14%, and a string 4%, ten of which
    contained the literal text "undefined". None is the one honest answer, and it is the
    single place this package departs from the reference on purpose.
    """
    assert implementation.decompress_from_base64(junk) is None


def test_a_truncated_payload_is_empty_not_partial(implementation, payload: str) -> None:
    # Half a payload must not come back as half a save — that would be a corrupt file
    # presented as a valid one.
    assert implementation.decompress_from_base64(payload[: len(payload) // 2]) == ""


def test_the_last_character_is_padding(implementation, payload: str) -> None:
    # The encoder always flushes one more character than the stream needs, so dropping it
    # changes nothing. This is why two implementations can differ in the tail and both be
    # right, and why the round-trip tests compare payloads rather than files.
    assert implementation.decompress_from_base64(payload.rstrip("=")[:-1]) == implementation.decompress_from_base64(payload)


def test_trailing_junk_after_the_end_marker_is_ignored(implementation, payload: str) -> None:
    assert implementation.decompress_from_base64(payload + "AAAA") == implementation.decompress_from_base64(payload)


def test_uri_variant_accepts_a_payload_that_travelled_through_a_query_string(implementation) -> None:
    # "+" becomes " " in a query string; the reference undoes that before decoding.
    encoded = implementation.compress_to_encoded_uri_component("gold" * 40)
    assert implementation.decompress_from_encoded_uri_component(encoded.replace("+", " ")) == "gold" * 40


def test_utf16_variant_ends_with_the_space_the_format_requires(implementation) -> None:
    assert implementation.compress_to_utf16('{"a":1}').endswith(" ")
