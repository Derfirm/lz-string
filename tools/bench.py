"""Reproduce the numbers in README.md and SPEC.md.

    python tools/bench.py                 # generated save-shaped payloads
    python tools/bench.py FILE [FILE ...] # real files (base64 lz-string payloads)

Three columns where they are available: what ships, the Python reference the tests hold it
against, and — when it happens to be importable, it is not a dependency — the `lzstring`
package from PyPI, for scale.

Absolute times on a laptop move by a factor of two between runs: thermal state, other load.
Read the columns against each other, not against a number you remember.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import lz_string as lz
from lz_string import _reference

try:
    from lzstring import LZString  # type: ignore[import-not-found]

    BASELINE: object | None = LZString()
except ImportError:
    BASELINE = None


def save_shaped(items: int) -> str:
    rng = random.Random(20260901)
    return json.dumps(
        {
            "system": {"@": "Game_System", "_saveCount": 12},
            "party": {"_gold": 8536, "_items": {str(i): rng.randrange(99) for i in range(items)}},
            "switches": {"_data": [rng.random() > 0.5 for _ in range(items)]},
            "variables": {"_data": [rng.randrange(10**6) for _ in range(items)]},
            "text": "Привет " * min(items, 200),
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )


def timed(work, *args):
    start = time.perf_counter()
    result = work(*args)
    return result, time.perf_counter() - start


def main(argv: list[str]) -> None:
    if argv:
        cases = [
            (Path(p).name[:18], lz.decompress_from_base64(Path(p).read_text(encoding="utf-8")) or "")
            for p in argv
        ]
    else:
        cases = [(f"{n} items", save_shaped(n)) for n in (200, 2_000, 20_000, 60_000)]

    implementations = [("shipped", lz), ("reference", _reference)]
    if BASELINE is not None:
        implementations.append(("lzstring(PyPI)", BASELINE))

    print(f"{'payload':16s} {'chars':>9s} " + " ".join(f"{name:>16s}" for name, _ in implementations))
    for name, text in cases:
        packed = lz.compress_to_base64(text)
        compressions, decompressions = [], []
        for _, module in implementations:
            # The PyPI package spells its methods in camelCase; ours are the module functions.
            compress = getattr(module, "compress_to_base64", None) or module.compressToBase64
            decompress = getattr(module, "decompress_from_base64", None) or module.decompressFromBase64
            _, taken = timed(compress, text)
            compressions.append(f"{taken:15.3f}s")
            _, taken = timed(decompress, packed)
            decompressions.append(f"{taken:15.3f}s")
        print(f"{name:16s} {len(text):9d} " + " ".join(decompressions) + "   <- decompress")
        print(f"{'':16s} {'':9s} " + " ".join(compressions) + "   <- compress")


if __name__ == "__main__":
    main(sys.argv[1:])
