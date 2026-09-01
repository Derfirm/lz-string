# Changelog

## 0.1.0 — unreleased

First version. What it is, and what took the effort:

- **Correct on UTF-16 code units.** lz-string is defined over them and a Python string is
  not; the boundary is converted rather than iterated, so an emoji is not written truncated
  and a lone surrogate — what a Twine journal is made of — survives untouched. This is the
  bug that makes `lzstring` 1.0.4 on PyPI corrupt saves silently.
- **Compiled, and required.** The extension is the implementation; an import without it
  raises instead of falling back to something slower with different bugs. 15–45x faster than
  the PyPI package on decompression.
- **Its own decoder.** The `lz-str` crate is used for compression only: its decompressor
  skips characters the reference reads as zero bits, collapses two distinct failures into
  one answer, and refuses a payload whose trailing padding character was trimmed.
- **Lets go of the interpreter** while it works, so running a call in a thread actually
  unblocks the caller.
- **A contract for damaged input**, taken from the reference and pinned by tests: `""` when
  the stream ran out, `None` when it was never a payload.

Held to `lz-string` 1.5.0 on npm: 1202 golden vectors across four transports and both
directions, 38 real production saves, 5000 fuzzed inputs, 16000 malformed probes, and the
whole suite run again inside the deployment image. See SPEC.md.
