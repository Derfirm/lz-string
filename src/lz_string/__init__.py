"""lz-string for Python, pinned to the behaviour of the JavaScript original.

The implementation is a compiled extension — the ``lz-str`` crate, corrected to the
reference, behind pyo3. It is required, not optional: ``pip install`` builds it, and an
install without it is an install that did not finish.

    >>> import lz_string as lz
    >>> lz.decompress_from_base64(lz.compress_to_base64('{"gold":9000}'))
    '{"gold":9000}'

Everything here is expressed in ``str``, and lz-string is defined over UTF-16 code units:
real saves contain lone surrogates, which are legal input and survive untouched. See
SPEC.md for the format, for the decoding contract on damaged input, and for the two places
the crate underneath had to be corrected.

A pure-Python implementation lives in ``_reference``. It is the test suite's second
opinion, not a fallback: nothing imports it at runtime.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lz-string")
except PackageNotFoundError:  # running from a checkout that was never installed
    __version__ = "0.0.0+source"

__all__ = (
    "LZString",
    "compress",
    "compress_to_base64",
    "compress_to_encoded_uri_component",
    "compress_to_utf16",
    "decompress",
    "decompress_from_base64",
    "decompress_from_encoded_uri_component",
    "decompress_from_utf16",
)

try:
    from lz_string import _native as _rs
except ImportError as error:  # pragma: no cover - the message is the point
    # "Missing" and "there but unloadable" send you to different places, and the second is
    # the likely one: an extension built against a newer glibc than the image it is being
    # installed into loads with `GLIBC_2.xx not found`, which is not a missing file at all.
    # Build the wheel on the distribution it will run on, or on manylinux.
    detail = str(error)
    raise ImportError(
        f"lz_string could not load its compiled extension: {detail}. "
        "Build it with `uv sync` (or `pip install .`), on the same platform and C library "
        "it will run on."
    ) from error


def _units(text: str) -> bytes:
    return text.encode("utf-16-le", "surrogatepass")


def _text(buf: bytes) -> str:
    return buf.decode("utf-16-le", "surrogatepass")


def compress(uncompressed: str | None) -> str:
    """Compress to a string of 16-bit code units (``LZString.compress``)."""
    if uncompressed is None:
        return ""
    return _text(_rs.compress(_units(uncompressed)))


def compress_to_base64(uncompressed: str | None) -> str:
    if uncompressed is None:
        return ""
    return _rs.compress_to_base64(_units(uncompressed))


def compress_to_encoded_uri_component(uncompressed: str | None) -> str:
    if uncompressed is None:
        return ""
    return _rs.compress_to_encoded_uri_component(_units(uncompressed))


def compress_to_utf16(uncompressed: str | None) -> str:
    if uncompressed is None:
        return ""
    return _rs.compress_to_utf16(_units(uncompressed))


def _decode(decoder, payload: str | None) -> str | None:
    # The three answers of the format, unchanged from the reference: "" for a payload that
    # ran out before the end marker, None for one that was never lz-string, and the string
    # otherwise. Nothing here raises on bad input — see SPEC.md, "Decoding contract".
    if payload is None:
        return ""
    if payload == "":
        return None
    # Payloads go in as UTF-16LE bytes, not str: a damaged one can hold a lone surrogate,
    # and pyo3 would refuse to build a &str from it.
    decoded = decoder(_units(payload))
    # The extension answers None for "not an lz-string payload" and bytes — possibly empty
    # — for everything the reference returns as a string.
    return None if decoded is None else _text(decoded)


def decompress(compressed: str | None) -> str | None:
    return _decode(_rs.decompress, compressed)


def decompress_from_base64(compressed: str | None) -> str | None:
    return _decode(_rs.decompress_from_base64, compressed)


def decompress_from_encoded_uri_component(compressed: str | None) -> str | None:
    return _decode(_rs.decompress_from_encoded_uri_component, compressed)


def decompress_from_utf16(compressed: str | None) -> str | None:
    return _decode(_rs.decompress_from_utf16, compressed)


class LZString:
    """Drop-in for the ``lzstring`` package on PyPI, whose method names are camelCase.

    Provided so an existing codebase can switch by changing one import line. New code
    should call the module-level functions instead.
    """

    @staticmethod
    def compress(uncompressed: str | None) -> str:
        return compress(uncompressed)

    @staticmethod
    def compressToBase64(uncompressed: str | None) -> str:
        return compress_to_base64(uncompressed)

    @staticmethod
    def compressToUTF16(uncompressed: str | None) -> str:
        return compress_to_utf16(uncompressed)

    @staticmethod
    def compressToEncodedURIComponent(uncompressed: str | None) -> str:
        return compress_to_encoded_uri_component(uncompressed)

    @staticmethod
    def decompress(compressed: str | None) -> str | None:
        return decompress(compressed)

    @staticmethod
    def decompressFromBase64(compressed: str | None) -> str | None:
        return decompress_from_base64(compressed)

    @staticmethod
    def decompressFromUTF16(compressed: str | None) -> str | None:
        return decompress_from_utf16(compressed)

    @staticmethod
    def decompressFromEncodedURIComponent(compressed: str | None) -> str | None:
        return decompress_from_encoded_uri_component(compressed)
