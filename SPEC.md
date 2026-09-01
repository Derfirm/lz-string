# The lz-string format

What is on disk, why the obvious Python port of it is wrong, and where the existing
implementations disagree. Everything here is checked by the test suite; where a claim came
from a measurement, the measurement is named.

The authority is **`lz-string` 1.5.0 on npm** — the JavaScript library the games write
their saves with. Where this document says "the reference", that is what it means.

---

## 1. The data model: UTF-16 code units

lz-string compresses a *JavaScript string*, which is a sequence of UTF-16 code units. A
Python string is a sequence of code points. Below U+FFFF the two agree; above it they do
not, and that gap is the single most common way a port goes wrong:

| | JavaScript | Python |
|---|---|---|
| `"a"` | 1 unit, 0x0061 | 1 code point, U+0061 |
| `"中"` | 1 unit, 0x4E2D | 1 code point, U+4E2D |
| an emoji U+1F600 | **2 units**, 0xD83D 0xDE00 | **1 code point**, U+1F600 |
| a lone half, U+D805 | 1 unit — legal, ordinary | 1 code point — legal, unencodable in UTF-8 |

Two consequences the API here is built around:

1. **Compression must iterate units, not code points.** The format has a 16-bit field for
   a new character; hand it U+1F600 whole and the value is written truncated. That is not
   hypothetical — see §7.
2. **Lone surrogates are ordinary input.** Twine's SugarCube stores some variables as a raw
   `LZString.compress()` blob, whose 16-bit output routinely lands in 0xD800–0xDFFF; a
   Degrees of Lewdity journal is made of them. Anything that routes a value through UTF-8
   without `errors="surrogatepass"` destroys such a save.

**Normalisation.** Decompression returns code units regrouped into code points, so
compressing `chr(0xD83D) + chr(0xDE00)` and decompressing gives back the single character
U+1F600. No unit is lost or altered; only their grouping, which JavaScript could not have
distinguished in the first place. A lone half stays exactly as it was.

## 2. The bit stream

LZW over code units, emitted least-significant-bit first into a bit stream. The decoder
reads a token of `numBits` bits at a time:

| token | meaning | followed by |
|---|---|---|
| `0` | a code unit below 256 appears for the first time | 8 bits, its value |
| `1` | a code unit of 256 or above appears for the first time | 16 bits, its value |
| `2` | end of stream | nothing |
| ≥ 3 | dictionary entry `token` | nothing |

State, all of it implied rather than stored:

- `dictSize` starts at 3 (tokens 0–2 are reserved) and grows by one per entry;
- `numBits` starts at 2 for the encoder's first token and 3 thereafter;
- `enlargeIn` counts down from 4; at zero, `numBits` grows by one and `enlargeIn` becomes
  `1 << numBits`. The counter is decremented in two places per iteration — once for a new
  character and once for the emitted token — and an off-by-one there only shows up after
  tens of thousands of characters, which is what the `large` vectors in the corpus are for.

Standard LZW rule for the entry being defined right now: a token equal to `dictSize` means
"the previous entry plus its own first character".

## 3. Packing into characters

The bit stream is cut into fixed-width characters. The width and alphabet are the only
difference between the four transports:

| function | bits/char | character | note |
|---|---|---|---|
| `compress` | 16 | the value itself | output is an arbitrary UTF-16 string, lone surrogates and all |
| `compress_to_utf16` | 15 | `chr(value + 32)` | stays inside the BMP; **a trailing space is part of the format** |
| `compress_to_base64` | 6 | `KEY_BASE64[value]` | padded with `=` to a multiple of 4 |
| `compress_to_encoded_uri_component` | 6 | `KEY_URI[value]` | `+` and `/` become `+` and `-`, `=` becomes `$`; no padding |

```
KEY_BASE64 = ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=
KEY_URI    = ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$
```

**The trailing character.** After the end marker the encoder flushes the accumulator by
shifting until the current character is full — *unconditionally*, so a stream that happens
to end on a boundary still gets one extra all-zero character. Padding is therefore always
1..bits_per_char bits, never zero. Skip that and you produce a payload the reference
decoder walks off the end of.

**The tail is don't-care.** Those padding bits carry nothing, so two encoders can emit
different final characters and both be right. Compare payloads, not files: the same input
compressed by different implementations may differ in the last character or two and still
decompress identically. The savefile-editor round-trip tests are written that way for
exactly this reason.

**`=` in the base64 alphabet.** `KEY_BASE64` has 65 entries: the reference maps `=` to the
value 64, and 64 AND any six-bit mask is zero — so padding contributes zero bits while still
counting towards the length the decoder may read. This package reaches the same result by
reading every character outside the alphabet as six zero bits; §4 explains why the tempting
shortcut of skipping them instead is wrong.

## 4. Decoding contract

Measured against the reference (lz-string 1.5.0, node 25), and pinned in
`tests/test_reference_behaviour.py`:

There are three answers, and which one you get is part of the format:

- **the string** — it decoded;
- **`""`** — the stream ran out before the end marker: truncated, or never a payload;
- **`None`** — a token named a dictionary entry that no encoder could have written, or the
  two-bit header was 3, which the format cannot produce. Not an lz-string payload at all.

| input | reference | this package |
|---|---|---|
| `None` | `""` | `""` |
| `""` | `null` | `None` |
| a valid payload | the string | the string |
| valid payload + junk after it | the string (stops at the end marker) | same |
| valid payload minus its last character | the string (that character is padding) | same |
| half a payload | `""` | `""` |
| `"!!!"`, `"===="`, `"A"` | `""` | `""` |
| `"+"` | `null` | `None` |
| `"zzzz"` | **throws TypeError** | `None` |

The last row is the only deliberate departure, and it is narrow: on a payload whose header
is impossible the reference carries a JavaScript `undefined` into its dictionary and blunders
on. Over 4000 such payloads that ended as `null` 67% of the time, `""` 15%, a `TypeError`
14%, and an actual string 4% — ten of which contained the literal text `undefined`. Nothing
here raises while decoding, and an impossible header answers `None`.

Getting this wrong is easy and quiet. Two examples from this package's own history, both
found by fuzzing against the reference rather than by reading the code:

- characters outside the alphabet were **dropped** rather than read as zero bits. The
  reference looks them up, gets `undefined`, ANDs it with the bit mask, and still counts
  them against the length it may read — so dropping them shortens the stream, and a payload
  whose base64 padding was its last chance to reach the end marker decoded to nothing. 61
  disagreements per 16000 malformed probes;
- `""` was returned where the reference returns `null`, collapsing "truncated" into "not a
  payload". 3930 probes.

## 5. What ships, and what the tests hold it to

The package is a compiled extension and nothing else; `pip install` builds it, and an
install without it is an install that did not finish.

- **both halves are ours** — `rust/src/decode.rs` and `rust/src/encode.rs`, ported from the
  reference rather than wrapped around a crate. The package has no Rust dependencies beyond
  pyo3. Why not [`lz-str`](https://crates.io/crates/lz-str), which exists and does this: §7.
- every string crosses the FFI boundary as **UTF-16LE bytes**, decoders included. pyo3
  cannot build a Rust `&str` from a Python string holding a lone surrogate and raises
  where the reference answers; and `String::from_utf16_lossy` coming back would replace such
  a unit with U+FFFD, destroying the save it was in.

A pure-Python implementation lives in `src/lz_string/_reference.py`. It is **not** a
fallback — nothing imports it at runtime. It exists so the suite has a second opinion that
is neither the extension under test nor a call out to node: every behavioural test runs
against both, and the golden corpus holds both to JavaScript.

## 6. Performance

One run, best of three, on two real saves, with everything measured the same way — the
earlier numbers in this file were stitched together from separate sessions and one of them
had tracemalloc running, which is its own lesson.

| payload | this package | the reference, in Python | PyPI `lzstring` |
|---|---|---|---|
| decompress 259 KB → 975 K characters | **0.004 s** | 0.064 s | 1.199 s |
| compress those 975 K characters | **0.044 s** | 0.207 s | 0.312 s |
| decompress 1.8 MB → 13.4 M characters | **0.054 s** | 0.453 s | 8.581 s |
| compress those 13.4 M characters | **1.547 s** | 3.878 s | 4.766 s |

`tools/bench.py FILE...` reproduces it. Absolute times on a laptop move by a factor of two
between runs; the columns are what matters.

Two structural choices account for most of it, and both were the same mistake in different
places: **the dictionary is not keyed by the string it matched.** The reference builds `w + c`
and looks that up, which in a typed language means a fresh buffer per prefix; the decoder
here stores each entry as a range into the output it has already written, and the encoder
keys its dictionary by `(code of w, c)` — two integers. Removing the per-token copy took
decompression from 0.45 s to 0.13 s on the large save before the machine settled; keying the
encoder by integers took compression from 5.2 s to 1.5 s.

**The extension releases the interpreter** while it works (`Python::detach` around every
call's Rust half; the argument is copied into owned data first). This is load-bearing rather
than tidy: the service this was written for awaits its unpacking inline in a request handler,
and the obvious remedy — run the call in a thread — does nothing at all if the extension
holds the GIL. Measured before the change, a neighbouring Python thread got 2 turns during a
0.26 s decompression and two compressions in two threads took exactly as long as one after
the other; after it, about half a million turns and 1.86 s against 2.86 s.

Peak memory on the 1.8 MB payload: 38 MiB compiled, 71 MiB in Python.

## 7. Divergences in other implementations

Measured over the same 1202 vectors.

### `lzstring` 1.0.4 (PyPI, pure Python)

| function | result |
|---|---|
| `compressToBase64` | **294 of 1202 vectors differ** from the reference |
| `compressToUTF16` | 294 differ |
| `compress` | 319 differ |
| `decompressFromUTF16` | **raises `TypeError` on every input** — it subtracts an int from a `str` |

The root cause of the mismatches is §1: it iterates code points. The visible effect:

```python
>>> LZString().compressToBase64('{"name":"Marie 😀"}')      # 1.0.4
'N4IgdghgtgpiBcICyEBOBLGACQAG8gL5A==='
>>> LZString().decompressFromBase64(_)
'{"name":"Marie "}'        # 0x1F600 truncated to 16 bits
```

The player's emoji comes back as U+F600, a private-use character. Any Python code that
writes saves through that package corrupts every save containing an astral character —
emoji in a character name, a nickname, a journal entry.

### `lz-str` 0.2.1 (crates.io, Rust)

This package started as a wrapper around it and no longer depends on it at all. The reasons
are worth keeping, because they are the reasons anyone reaching for that crate should know.

Its **compressor** is byte-identical to the reference except for base64 padding: it appends
one `=` too many (701 of 1202 vectors; the payload before the padding is identical in every
one). Correct output, then, but it inherits the reference's string-keyed dictionary, which
allocates a buffer per prefix — compression through it took 4.8 s where the encoder here
takes 1.5 s.

Its **decompressor** has three problems, which is what made wrapping it untenable:

- it **skips a character outside the alphabet** instead of reading it as zero bits while
  still counting it — the mirror of the bug in §4, and it shifts every following bit;
- it **collapses the two failure modes** into one answer, losing the distinction a caller
  needs;
- it **refuses a payload whose final, all-padding character was trimmed**, which the
  reference still reads.

Wrapping around those from Python meant routing suspect payloads back to a Python decoder —
which works, but leaves the shipped package half implemented in the slow language on exactly
the inputs where being right matters. The decoder here is about 130 lines and has none of the
three; once the encoder followed, for speed, the dependency had nothing left to do.

The one correction still applied to the crate — the base64 padding — lives where the
padding is produced, in `rust/src/lib.rs`, and is pinned by `tests/test_parity.py`, so a
release that fixes it upstream fails loudly rather than being corrected twice.

## 8. Regenerating the corpus

```bash
npm --prefix tools install     # once: pulls lz-string
node tools/gen_vectors.mjs     # -> tests/data/vectors.jsonl.gz
```

The generator is deterministic (fixed seed), so a regenerated file that differs means the
reference changed — which is exactly the diff you want to look at. 1202 vectors: a sweep of
all 65536 code units, lone surrogates, astral characters, save-shaped JSON, degenerate
inputs, incompressible noise, and payloads up to 250 KB.

## 9. How the claims here were checked

| check | scale | result |
|---|---|---|
| golden corpus vs. node | 1202 vectors x 4 transports x 2 directions x 2 implementations | identical |
| real production saves | 38 files (plain MV, obfuscated MV, Twine incl. the surrogate journal, up to 1.8 MB), decompress **and** recompress | identical |
| | *the files themselves are other people's saves and are not in this repository; the harness takes paths, so the row is reproducible with your own* | |
| differential fuzz vs. node | 5000 generated inputs x 4 transports x 2 implementations (`tools/fuzz_against_node.py`) | identical |
| malformed-input fuzz | 16000 probes x 2 implementations (same harness, `--junk`) | agree with each other and with the reference; nothing raised |
| mutation testing | 10 deliberate defects reintroduced one at a time | 9 caught by the suite; the 10th turned out to be dead code and was deleted |
| Linux, host architecture | built and run in `python:3.12.11-slim-bullseye`, the target image (`tools/check_linux.sh`) | 251 passed |
| Linux, x86_64 | the same, cross-compiled, run under emulation (`tools/check_linux.sh linux/amd64`) | 251 passed |
| glibc | a bookworm-built extension on bullseye | refuses to load — build where it will run |

The malformed-input fuzz is the one that found real bugs — three of them, two in this
package. Everything above it passed while they were still there. Mutation testing is what
says the tests that now cover them can actually fail: a suite that cannot go red is the
failure mode that produced GitLab #72 in the project this was written for.
