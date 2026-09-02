# lzstring-codec

[![PyPI](https://img.shields.io/pypi/v/lzstring-codec)](https://pypi.org/project/lzstring-codec/)
[![Python](https://img.shields.io/pypi/pyversions/lzstring-codec)](https://pypi.org/project/lzstring-codec/)
[![CI](https://github.com/Derfirm/lz-string/actions/workflows/ci.yml/badge.svg)](https://github.com/Derfirm/lz-string/actions/workflows/ci.yml)
[![Licence](https://img.shields.io/pypi/l/lzstring-codec)](LICENSE)

lz-string for Python that agrees with the JavaScript original, byte for byte.

```bash
pip install lzstring-codec      # or: uv add lzstring-codec
```

```python
import lz_string as lz

lz.compress_to_base64('{"gold":9000}')     # 'N4Ig5g9gNgJiBcBOADKgvkA='
lz.decompress_from_base64(_)               # '{"gold":9000}'
```

Installed as `lzstring-codec`, imported as `lz_string`. The obvious distribution name is not
available: PyPI refuses it as too similar to `lzstring`, which is one of the packages this
exists to replace.

## Why it exists

The two lz-string ports already on PyPI corrupt save files, quietly, in the same way:

```python
>>> import lzstring                                  # the package on PyPI
>>> s = lzstring.LZString()
>>> s.decompressFromBase64(s.compressToBase64('{"name":"Marie 😀"}'))
'{"name":"Marie \uf600"}'      # U+F600, a private-use box
```

The emoji is gone, replaced by a private-use character the game will draw as an empty box.
Nothing raises; the save is simply not the one the player had.

The cause is a single mismatch. lz-string is defined over UTF-16 code units, which is what a
JavaScript string is made of; a Python string is a sequence of code points. Below U+FFFF the
two agree, so most saves survive and the bug stays invisible — but an emoji is one Python
character and two JavaScript ones, and written whole into a field that holds sixteen bits it
comes back truncated. Both `lzstring` 1.0.4 and `py-lzstring` 0.1.1, written by different
people, make exactly this mistake. It is the obvious way to port the code, and it is wrong.

This package converts at the boundary instead, so an emoji survives — and so does a lone
surrogate half, which is legal in this format and which a Twine journal is full of.

## What "correct" means here

That every function returns what the JavaScript library returns, for the same input, in the
same bytes. Not "it round-trips": a codec can round-trip perfectly with itself and still hand
the game something it cannot read.

So the oracle is the reference itself — `lz-string` 1.5.0 on npm, the library the games
compress with — asked directly by running it in node, across all four transports and both
directions, over inputs chosen to be awkward: every one of the 65536 code units, lone
surrogates in every position, astral characters, and the shape of a real save.

Two things that are easy not to think about, and are checked:

- **Damaged payloads.** A truncated file, a stray character, a header the format cannot
  produce — the reference distinguishes "the stream ran out" from "this was never a payload",
  and a caller cares which. Fuzzing that boundary against node is what found the last two
  bugs in this package, both invisible to every test that used only valid data.
- **The interpreter is released** while the extension works, so running a call in a thread
  actually unblocks the caller. Holding the GIL through a multi-second compression would make
  the obvious remedy do nothing at all.

[SPEC.md](SPEC.md) is the format written down: the bit stream, the contract on damaged input,
and where every other implementation departs from it.

## Fast, because of one decision

Both halves are compiled, and neither keys its dictionary by the string it matched. The
reference builds `w + c` and looks that up, which in a typed language means an allocation per
prefix; the decoder here stores each entry as a range into the output it has already written,
and the encoder keys its dictionary by `(code of w, unit)` — two integers. On two real saves:

| | decompress | compress |
|---|---|---|
| **lzstring-codec**, 259 KB → 975 K chars | **0.004 s** | **0.044 s** |
| `lzstring` 1.0.4, the same file | 1.199 s | 0.312 s |
| **lzstring-codec**, 1.8 MB → 13.4 M chars | **0.054 s** | **1.547 s** |
| `lzstring` 1.0.4, the same file | 8.581 s | 4.766 s |

`tools/bench.py FILE...` reproduces it on your own payloads.

## Migrating from `lzstring`

One import line — the camelCase class exists for exactly this:

```diff
-from lzstring import LZString
+from lz_string import LZString
```

Two behaviour changes, both improvements: saves with astral characters stop being corrupted,
and `decompressFromUTF16`, which raised `TypeError` on every input it was ever given, works.

## Working on it

```bash
uv sync --extra dev                          # builds the extension in place
uv run pytest                                # every behavioural test runs twice: against the
                                             # extension and against the Python reference
uv sync --reinstall-package lzstring-codec   # after touching the Rust
./tools/check_linux.sh                       # and the whole suite inside the deployment image
```

`src/lz_string/_reference.py` is a complete implementation in Python. It is the suite's
second opinion, not a fallback: nothing imports it at runtime, and a disagreement between it
and the extension fails a test instead of reaching someone's save.

The Linux run is not ceremony. It builds inside `python:3.12.11-slim-bullseye` — the image
this package is destined for — because an extension linked against a newer glibc compiles
cleanly and then refuses to load, which is a thing to find out before a deploy rather than
during one.

Two more harnesses, both needing node: `tools/gen_vectors.mjs` regenerates the golden corpus
(deterministic — a diff means the reference moved), and `tools/fuzz_against_node.py` goes
wider than the corpus, over generated inputs, damaged payloads, and real files you point it
at.

## Releasing

By tag. Bump `version` in `pyproject.toml`, note it in `CHANGELOG.md`, then:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

The workflow refuses a tag that disagrees with the version, builds wheels for Linux and macOS
on both architectures plus an sdist, uploads, and then asks PyPI whether the version is
really there — an upload that uploaded nothing exits zero otherwise. `workflow_dispatch` runs
all of it except the upload, which is how the pipeline is tested without releasing anything.

## Provenance and licence

MIT (`LICENSE`). The only dependency is [pyo3](https://pyo3.rs) (MIT/Apache-2.0); both halves
of the codec are ports of [pieroxy/lz-string](https://github.com/pieroxy/lz-string) (MIT),
which is also the reference every claim here is measured against. `THIRD_PARTY.md` carries
the notices, and SPEC.md §7 explains why the obvious Rust dependency was dropped rather than
wrapped.

No user data is in this repository: every test input is generated, and the corpus is the
reference implementation's own output.
