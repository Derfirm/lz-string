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
uv add git+ssh://git@github.com/Derfirm/lz-string.git    # or, in a checkout:
uv sync                                                  # builds the extension in place
pip install .                                            # pip works too; maturin does the build
```

An import without the extension raises rather than falling back to something slower and
subtly different.

**Build it where it will run.** The binary is tied to the C library it was linked against:
one built on Debian bookworm (glibc 2.36) will not load on bullseye (2.31), which is what
`python:3.12.11-slim-bullseye` — the image this package is destined for — is built on. It
fails at import with `GLIBC_2.34 not found`, not at build time. Either build inside the
target image, or produce a manylinux wheel.

On two real saves, best of three in one run:

| | decompress | compress |
|---|---|---|
| **this package**, 259 KB → 975 K chars | **0.004 s** | **0.044 s** |
| `lzstring` 1.0.4, the same | 1.199 s | 0.312 s |
| **this package**, 1.8 MB → 13.4 M chars | **0.054 s** | **1.547 s** |
| `lzstring` 1.0.4, the same | 8.581 s | 4.766 s |

Both halves are ours, and the only Rust dependency is pyo3. The obvious alternative,
the [`lz-str`](https://crates.io/crates/lz-str) crate, was the starting point and did not
survive contact with damaged input: it answers the same thing for two failures the reference
keeps apart, skips characters the reference reads as zero bits, and refuses a payload whose
trailing padding character was trimmed. SPEC.md §7 has the measurements.

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
uv sync --extra dev                      # .python-version pins 3.12, as in production
uv run pytest                            # every test runs against both implementations
uv sync --reinstall-package lz-string    # after touching the Rust: rebuild the extension
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

## Releasing

By tag, not by merge. Most merges here are documentation and CI, and PyPI refuses a second
upload of the same version — publishing on merge would mean either a version bump per commit
or a release job that fails as a matter of course.

```bash
# bump `version` in pyproject.toml, note it in CHANGELOG.md, merge, then:
git tag v0.1.0 && git push origin v0.1.0
```

The workflow builds wheels for linux and macOS on both architectures plus an sdist, checks
that the tag and the version in pyproject.toml say the same thing, and stops in front of the
upload: that step lives in a `pypi` environment, so it waits for an approval and for the
`PYPI_API_TOKEN` secret kept there. `workflow_dispatch` runs everything except the upload,
which is how the pipeline gets tested without releasing anything.

## Provenance and licence

MIT (`LICENSE`). Compression comes from the [`lz-str`](https://crates.io/crates/lz-str)
crate and the bindings from [pyo3](https://pyo3.rs), both MIT/Apache-2.0; the decoder is a
port of [pieroxy/lz-string](https://github.com/pieroxy/lz-string), MIT, which is also the
reference every claim here is measured against. See `THIRD_PARTY.md`.

No user data lives in this repository: every test input is generated, and the corpus is the
reference implementation's own output.
