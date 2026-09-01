# Third-party notices

The compiled extension links the crates below; their notices are reproduced as their
licences require. The Python and Rust code in this repository is MIT, see `LICENSE`.

## lz-str

<https://crates.io/crates/lz-str> — MIT OR Apache-2.0. A Rust port of lz-string, used here
for compression. This package does not use its decompressor; see SPEC.md §7 for why.

## pyo3

<https://crates.io/crates/pyo3> — MIT OR Apache-2.0. The Python bindings.

## lz-string (JavaScript)

<https://github.com/pieroxy/lz-string> — MIT, by Pieroxy. Not linked or redistributed: it is
the *reference*. Its behaviour is what this package is measured against, and the golden
vectors in `tests/data/vectors.jsonl.gz` are its output, produced by `tools/gen_vectors.mjs`.
Everything this package claims about correctness is a claim about agreeing with it.
