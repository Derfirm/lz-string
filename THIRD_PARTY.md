# Third-party notices

The Python and Rust code in this repository is MIT, see `LICENSE`. The compiled extension
links one crate, and its notice is reproduced as its licence requires.

## pyo3

<https://crates.io/crates/pyo3> — MIT OR Apache-2.0. The Python bindings.

## lz-string (JavaScript)

<https://github.com/pieroxy/lz-string> — MIT, by Pieroxy. Not linked or redistributed: it is
the *reference*. Both halves of the codec here are ports of it, its behaviour is what this
package is measured against, and the golden vectors in `tests/data/vectors.jsonl.gz` are its
output, produced by `tools/gen_vectors.mjs`. Everything this package claims about correctness
is a claim about agreeing with it.

## lz-str (Rust) — no longer a dependency

<https://crates.io/crates/lz-str> — MIT OR Apache-2.0. This package wrapped it until its
decompressor turned out to disagree with the reference on damaged input in three ways
(SPEC.md §7). Nothing of it ships here now; the note is kept because the analysis in SPEC.md
refers to it.
