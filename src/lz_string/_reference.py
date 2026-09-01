"""The reference implementation, in Python. Not the one the package ships.

This module exists so the test suite has a second opinion that is not the extension under
test and not a network call to node: every behavioural test runs against both this and the
shipped Rust path, and the golden corpus holds them both to the JavaScript original.

It is deliberately not exported. Importing it at runtime would give you a working but
15x slower lz-string, which is not what this package is for.

The same bit stream as the JavaScript original.

The algorithm is LZW over UTF-16 code units, packed into a bit stream that is then cut
into characters of 6, 15 or 16 bits (see SPEC.md). This module is a rewrite rather than a
transliteration: the reference implementations walk the stream one bit at a time in an
interpreted loop, which is what makes the PyPI ``lzstring`` package tens of times slower
than it needs to be. Here the whole stream is materialised once as a string of "0"/"1",
and every read is a slice.

Everything is expressed in ``str`` because lz-string is defined over UTF-16 code units:
real saves contain lone surrogates (a Degrees of Lewdity journal, for one), which are
legal here and must survive untouched. Never route a value through UTF-8 without
``errors="surrogatepass"``.
"""

from __future__ import annotations

from struct import unpack

__all__ = (
    "compress",
    "compress_to_base64",
    "compress_to_encoded_uri_component",
    "compress_to_utf16",
    "decompress",
    "decompress_from_base64",
    "decompress_from_encoded_uri_component",
    "decompress_from_utf16",
)

def _to_units(text: str) -> str:
    """Split astral characters into their UTF-16 halves.

    lz-string is defined over UTF-16 code units, which is what a JavaScript string is made
    of; a Python string is made of code points. For everything up to U+FFFF the two agree,
    but U+1F600 is one Python character and two JavaScript ones — feed it in whole and the
    compressor writes a 17-bit value into a 16-bit field, which is exactly how the PyPI
    ``lzstring`` package corrupts every save containing an emoji (see SPEC.md).
    """
    if text.isascii() or max(text) <= "\uffff":
        return text
    units = text.encode("utf-16-le", "surrogatepass")
    return "".join(map(chr, unpack("<%dH" % (len(units) // 2), units)))


def _from_units(text: str) -> str:
    """Undo :func:`_to_units`: rejoin surrogate halves, leave lone surrogates alone."""
    if text.isascii():
        return text
    # encode/decode with surrogatepass is a C-level pass that recombines valid pairs and
    # carries lone surrogates through untouched -- the DoL journal depends on the second half.
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


KEY_BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
KEY_URI = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$"

class _BitTable(dict):
    """Translation table char -> bits. A character outside the alphabet reads as zeros.

    Not "is skipped": the reference looks the character up, gets undefined, and ANDs it
    with the bit mask, which yields zero bits — and, critically, still counts the character
    against the length it is allowed to read. Dropping such characters instead shortens the
    stream, and a payload whose base64 padding was its last chance to reach the end marker
    then decodes to nothing where JavaScript decodes it fine. Measured on 4000 malformed
    payloads: dropping them put this backend at odds with the reference 61 times.

    The same rule covers "=": the reference maps it to 64, and 64 AND any six-bit mask is 0.
    """

    def __missing__(self, key: int) -> str:
        return "000000"


# char -> its bits, in the order the decoder reads them (most significant first).
_BASE64_BITS = _BitTable({ord(c): format(i, "06b") for i, c in enumerate(KEY_BASE64[:64])})
# KEY_URI[64] is "$", the counterpart of base64's "=": the reference maps it to 64, which
# no six-bit read returns, so it belongs with the characters that read as zeros.
_URI_BITS = _BitTable({ord(c): format(i, "06b") for i, c in enumerate(KEY_URI[:64])})
_BYTE_BITS = [format(i, "08b") for i in range(256)]


def _stream_from_base64(text: str) -> str:
    return text.translate(_BASE64_BITS)


def _stream_from_uri(text: str) -> str:
    # A URI-safe payload that travelled through a query string has its "+" turned into a
    # space; the reference undoes that before decoding, so do it here too.
    return text.replace(" ", "+").translate(_URI_BITS)


def _stream_from_utf16(text: str) -> str:
    # Masked to 15 bits because the reference reads bits as `value & position`, and position
    # never rises above 1 << 14: a character outside the format's range contributes only its
    # low bits, and one below the +32 offset contributes its two's complement. Formatting the
    # raw difference instead would inject extra bits and desynchronise the whole stream.
    return "".join([format((ord(c) - 32) & 0x7FFF, "015b") for c in _to_units(text)])


def _stream_from_raw(text: str) -> str:
    # 16 bits per character is exactly the UTF-16 big-endian encoding of the string, so the
    # bit stream can be built from bytes instead of from per-character formatting.
    return "".join(map(_BYTE_BITS.__getitem__, text.encode("utf-16-be", "surrogatepass")))


def _decompress_stream(bits: str) -> str | None:
    """Decode a bit stream, the way the reference does, and never raise.

    Two different failures, two different answers, both taken from the original:

    * ``""`` — the stream ran out before the end marker: a truncated or nonsense payload;
    * ``None`` — a token named a dictionary entry that no encoder could have written, so
      this is not an lz-string payload at all.

    The reference throws a TypeError on some inputs in the second class; raising is the one
    behaviour here that is deliberately not reproduced.
    """
    pos = 0
    end = len(bits)
    if not bits:
        return ""

    def read(width: int) -> int:
        nonlocal pos
        chunk = bits[pos : pos + width]
        pos += width
        # The value's first bit is its least significant one, so reverse before parsing.
        return int(chunk[::-1], 2) if chunk else 0

    kind = read(2)
    if kind == 2:
        return ""
    if kind == 3:
        # No such header exists. The reference has no branch for it either: it carries a
        # JavaScript `undefined` into the dictionary and blunders on, which over 4000
        # malformed payloads ended as null 67% of the time, "" 15%, a TypeError 14%, and a
        # string 4% -- ten of which contained the literal text "undefined". That is not
        # behaviour to reproduce; a payload with an impossible header is not a payload.
        return None
    first = chr(read(8 if kind == 0 else 16))

    dictionary = ["", "", "", first]
    result = [first]
    w = first
    enlarge_in = 4
    dict_size = 4
    num_bits = 3

    while pos < end:
        code = read(num_bits)
        if code < 2:
            dictionary.append(chr(read(8 if code == 0 else 16)))
            code = dict_size
            dict_size += 1
            enlarge_in -= 1
        elif code == 2:
            return _from_units("".join(result))

        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1

        if code < len(dictionary):
            entry = dictionary[code]
        elif code == dict_size:
            entry = w + w[0]
        else:
            return None  # a code no encoder could have written: not an lz-string payload

        result.append(entry)
        dictionary.append(w + entry[0])
        dict_size += 1
        enlarge_in -= 1
        w = entry
        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1

    # Ran out of bits without meeting the end marker: a truncated payload. The reference
    # returns "" here; keep that, so a caller cannot mistake damage for an empty save.
    return ""


def _compress_stream(text: str) -> list[str]:
    """Return the bit stream as a list of chunks, each already in write order."""
    out: list[str] = []

    def write(value: int, width: int) -> None:
        out.append(format(value, "0%db" % width)[::-1])

    def write_new_char(char: str, num_bits: int) -> None:
        code_unit = ord(char)
        if code_unit < 256:
            write(0, num_bits)
            write(code_unit, 8)
        else:
            write(1, num_bits)
            write(code_unit, 16)

    dictionary: dict[str, int] = {}
    pending: set[str] = set()
    w = ""
    enlarge_in = 2  # compensates for the first entry, which must not count
    dict_size = 3
    num_bits = 2

    for c in _to_units(text):
        if c not in dictionary:
            dictionary[c] = dict_size
            dict_size += 1
            pending.add(c)

        wc = w + c
        if wc in dictionary:
            w = wc
            continue

        if w in pending:
            write_new_char(w[0], num_bits)
            pending.discard(w)
            enlarge_in -= 1
            if enlarge_in == 0:
                enlarge_in = 1 << num_bits
                num_bits += 1
        else:
            write(dictionary[w], num_bits)

        enlarge_in -= 1
        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1

        dictionary[wc] = dict_size
        dict_size += 1
        w = c

    if w != "":
        if w in pending:
            write_new_char(w[0], num_bits)
            pending.discard(w)
            enlarge_in -= 1
            if enlarge_in == 0:
                enlarge_in = 1 << num_bits
                num_bits += 1
        else:
            write(dictionary[w], num_bits)
        enlarge_in -= 1
        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1

    write(2, num_bits)  # end marker
    return out


def _pack(chunks: list[str], bits_per_char: int) -> str:
    bits = "".join(chunks)
    # The reference always flushes one more character, even when the stream happens to end
    # on a character boundary — so the padding is 1..bits_per_char bits, never zero. Getting
    # this wrong yields a payload the reference decoder walks off the end of.
    bits += "0" * (bits_per_char - len(bits) % bits_per_char)
    return bits


def _emit(bits: str, bits_per_char: int, table: str | None, offset: int = 0) -> str:
    values = (int(bits[i : i + bits_per_char], 2) for i in range(0, len(bits), bits_per_char))
    if table is not None:
        return "".join([table[v] for v in values])
    return "".join([chr(v + offset) for v in values])


def compress(uncompressed: str | None) -> str:
    """Compress to a string of 16-bit code units (``LZString.compress``)."""
    if uncompressed is None:
        return ""
    return _from_units(_emit(_pack(_compress_stream(uncompressed), 16), 16, None))


def compress_to_base64(uncompressed: str | None) -> str:
    if uncompressed is None:
        return ""
    packed = _emit(_pack(_compress_stream(uncompressed), 6), 6, KEY_BASE64)
    return packed + "=" * (-len(packed) % 4)


def compress_to_encoded_uri_component(uncompressed: str | None) -> str:
    if uncompressed is None:
        return ""
    return _emit(_pack(_compress_stream(uncompressed), 6), 6, KEY_URI)


def compress_to_utf16(uncompressed: str | None) -> str:
    if uncompressed is None:
        return ""
    # The trailing space is part of the format: the reference appends one unconditionally.
    return _emit(_pack(_compress_stream(uncompressed), 15), 15, None, offset=32) + " "


def decompress(compressed: str | None) -> str | None:
    if compressed is None:
        return ""
    if compressed == "":
        return None
    return _decompress_stream(_stream_from_raw(compressed))


def decompress_from_base64(compressed: str | None) -> str | None:
    if compressed is None:
        return ""
    if compressed == "":
        return None
    return _decompress_stream(_stream_from_base64(compressed))


def decompress_from_encoded_uri_component(compressed: str | None) -> str | None:
    if compressed is None:
        return ""
    if compressed == "":
        return None
    return _decompress_stream(_stream_from_uri(compressed))


def decompress_from_utf16(compressed: str | None) -> str | None:
    if compressed is None:
        return ""
    if compressed == "":
        return None
    return _decompress_stream(_stream_from_utf16(compressed))
