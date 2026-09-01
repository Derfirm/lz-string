# lz-string

lz-string for Python, held byte-for-byte to the JavaScript original.

It exists because the package that *is* on PyPI gets the format wrong in ways that quietly
corrupt real save files. It was written for [saveeditor.online](https://saveeditor.online),
which reads a few thousand lz-string saves a week and cannot afford to hand any of them back
altered.

```python
import lz_string as lz

lz.compress_to_base64('{"gold":9000}')          # 'N4Ig5g9gNgJiBcBOADKgvkA='
lz.decompress_from_base64(_)                    # '{"gold":9000}'
```

## Why

`lzstring` 1.0.4 on PyPI is a line-by-line transliteration of the JavaScript, and it
inherits neither its speed nor its correctness. Measured against 1202 vectors produced by
`lz-string` 1.5.0 on npm — the library the games themselves use:

- **294 vectors compress to different bytes**, because it walks Python code points where
  the format is defined over UTF-16 code units. In practice: an emoji in a player's name is
  written truncated, and the game reads back `U+F600`, a private-use box. Every save with an
  astral character is corrupted on write.
- **`decompressFromUTF16` raises `TypeError` on every input.** It subtracts an integer from
  a string. The function has never worked.
- Decompression rebuilds a 65-entry alphabet table *per character* and reads the bit stream
  one bit at a time: **22 seconds** for a 1.8 MB save, on the request path.

This package is byte-identical to the reference on all 1202 vectors, in all four
transports, in both directions, on both backends — and 15–45× faster.

How far that was pushed, because "it round-trips" is not the same as "it is right":

| check | scale | result |
|---|---|---|
| golden corpus vs. node | 1202 vectors x 4 transports x 2 directions x 2 backends | identical |
| real production saves | 38 files up to 1.8 MB, decompress **and** recompress | identical |
| differential fuzz vs. node | 5000 generated inputs x 4 transports x 2 backends | identical |
| malformed-input fuzz | 16000 probes x 2 backends | agree with each other and with the reference; nothing raised |

The last row is the one that found bugs — two of them in this package, both invisible to
every check above it, and both now pinned by tests. SPEC.md §4 says what they were.

See [SPEC.md](SPEC.md) for the format itself and for the full divergence table.

## Installing

The package is a compiled extension; `pip install` builds it, and a Rust toolchain is
required to do so.

```bash
pip install git+ssh://git@github.com/Derfirm/lz-string.git   # or a checkout:
pip install .                  # maturin builds the extension into the package
./tools/build_rust.sh          # or, for working in the checkout: -> src/lz_string/
```

An import without the extension raises rather than falling back to something slower and
subtly different.

**Build it where it will run.** The binary is tied to the C library it was linked against:
one built on Debian bookworm (glibc 2.36) will not load on bullseye (2.31), which is what
`python:3.12.11-slim-bullseye` — the image this package is destined for — is built on. It
fails at import with `GLIBC_2.34 not found`, not at build time. Either build inside the
target image, or produce a manylinux wheel.

| | decompress 259 KB | decompress 1.8 MB | compress 259 KB |
|---|---|---|---|
| this package | 0.08 s | 0.45 s | 0.27 s |
| *(`lzstring` 1.0.4, for scale)* | 3.25 s | 22.1 s | 1.13 s |

Compression comes from the [`lz-str`](https://crates.io/crates/lz-str) crate. Decompression
is ours: the crate answers the same thing for two failures the reference keeps apart, skips
characters the reference reads as zero bits, and refuses a payload whose trailing padding
character was trimmed. SPEC.md §7 has the measurements.

A pure-Python implementation of the whole format lives in `src/lz_string/_reference.py`.
It is the test suite's second opinion, not a fallback: nothing imports it at runtime.

## Migrating from `lzstring`

The camelCase API is provided as-is, so the change is one import line:

```python
-from lzstring import LZString
+from lz_string import LZString
```

Two behaviour changes to know about, both improvements, both in SPEC.md: saves containing
astral characters stop being corrupted, and `decompressFromUTF16` starts working.

## Tests

```bash
python -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m pytest             # every test runs against both implementations
./tools/check_linux.sh                   # built and run inside the target image (needs docker)
./tools/check_linux.sh linux/amd64       # and on production's architecture, cross-compiled
```

The Linux run is not ceremony. It is done in `python:3.12.11-slim-bullseye` — the exact image
this is destined for — and it has already caught two things a laptop cannot: a test that
measured the machine rather than the code, and an extension that built cleanly and then
refused to load because it wanted a newer glibc than the image has.

251 tests: the golden corpus per category and transport, the documented behaviour on damaged
input, seeded round-trips over random code units and surrogate halves, parity between the
shipped extension and the Python reference — including a fuzz of malformed payloads, which
is what pins the three corrections the crate underneath needed — and two tests that the
extension really does let go of the interpreter while it works.

To regenerate the corpus (deterministic — a diff means the reference moved):

```bash
npm --prefix tools install
node tools/gen_vectors.mjs
```

`tools/bench.py` reproduces the numbers above.

## Provenance and licence

MIT (`LICENSE`). Compression comes from the [`lz-str`](https://crates.io/crates/lz-str)
crate and the bindings from [pyo3](https://pyo3.rs), both MIT/Apache-2.0; the decoder is a
port of [pieroxy/lz-string](https://github.com/pieroxy/lz-string), MIT, which is also the
reference every claim here is measured against. See `THIRD_PARTY.md`.

No user data lives in this repository: every test input is generated, and the corpus is the
reference implementation's own output.
