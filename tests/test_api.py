"""The surface a caller sees: names, the camelCase compatibility class, the contract types."""

from __future__ import annotations

import inspect

import pytest

import lz_string as lz

FUNCTIONS = (
    "compress",
    "compress_to_base64",
    "compress_to_encoded_uri_component",
    "compress_to_utf16",
    "decompress",
    "decompress_from_base64",
    "decompress_from_encoded_uri_component",
    "decompress_from_utf16",
)

# The names the PyPI ``lzstring`` package uses, mapped to ours. Swapping one import is the
# whole migration, so every one of these has to exist and agree.
CAMEL_CASE = {
    "compress": "compress",
    "compressToBase64": "compress_to_base64",
    "compressToUTF16": "compress_to_utf16",
    "compressToEncodedURIComponent": "compress_to_encoded_uri_component",
    "decompress": "decompress",
    "decompressFromBase64": "decompress_from_base64",
    "decompressFromUTF16": "decompress_from_utf16",
    "decompressFromEncodedURIComponent": "decompress_from_encoded_uri_component",
}

# Which compressor produces input for which decompressor.
PAIRS = {
    "decompress": "compress",
    "decompressFromBase64": "compressToBase64",
    "decompressFromUTF16": "compressToUTF16",
    "decompressFromEncodedURIComponent": "compressToEncodedURIComponent",
}


@pytest.mark.parametrize("name", FUNCTIONS)
def test_every_function_is_exported(name: str) -> None:
    assert name in lz.__all__
    assert callable(getattr(lz, name))


def test_the_reference_is_not_part_of_the_public_surface() -> None:
    # It exists for the tests. Exporting it would invite someone to depend on the slow path.
    assert "_reference" not in lz.__all__


@pytest.mark.parametrize("camel,snake", CAMEL_CASE.items())
def test_compat_class_mirrors_the_module(camel: str, snake: str) -> None:
    method = getattr(lz.LZString, camel)
    assert inspect.isfunction(method) or inspect.ismethod(method)
    payload = '{"gold":9000,"name":"Marie"}'
    if camel.startswith("compress"):
        assert method(payload) == getattr(lz, snake)(payload)
    else:
        compressed = getattr(lz.LZString, PAIRS[camel])(payload)
        assert method(compressed) == getattr(lz, snake)(compressed) == payload


def test_compat_class_round_trips_through_each_pair() -> None:
    payload = '{"switches":[true,false],"name":"Marie"}'
    lzs = lz.LZString
    assert lzs.decompressFromBase64(lzs.compressToBase64(payload)) == payload
    assert lzs.decompressFromUTF16(lzs.compressToUTF16(payload)) == payload
    assert lzs.decompressFromEncodedURIComponent(lzs.compressToEncodedURIComponent(payload)) == payload
    assert lzs.decompress(lzs.compress(payload)) == payload


def test_the_three_return_types_are_what_the_contract_says() -> None:
    # A caller distinguishing "empty save" from "broken file" relies on exactly this.
    assert isinstance(lz.decompress_from_base64(lz.compress_to_base64("x")), str)
    assert lz.decompress_from_base64("") is None      # nothing to decode
    assert lz.decompress_from_base64("+") is None     # not an lz-string payload
    assert lz.decompress_from_base64("A") == ""       # ran out before the end marker
