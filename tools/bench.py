"""Reproduce the numbers in README.md and SPEC.md.

    python tools/bench.py                 # generated save-shaped payloads
    python tools/bench.py FILE [FILE ...] # real files (base64 lz-string payloads)

The PyPI ``lzstring`` package is included as a baseline when it happens to be importable;
it is not a dependency of this project.

Absolute times on a laptop move by a factor of two between runs — thermal state, other
load. Read the columns against each other, not against a number you remember.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import lz_string as lz  # noqa: E402
from lz_string import _python  # noqa: E402

try:
    from lzstring import LZString  # type: ignore

    BASELINE = LZString()
except ImportError:
    BASELINE = None

try:
    from lz_string import _rust
except ImportError:
    _rust = None


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


def timed(fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    return result, time.perf_counter() - start


def main(argv: list[str]) -> None:
    if argv:
        payloads = [(Path(p).name[:18], Path(p).read_text()) for p in argv]
        cases = [(name, lz.decompress_from_base64(text) or "") for name, text in payloads]
    else:
        cases = [(f"{n} items", save_shaped(n)) for n in (200, 2_000, 20_000, 60_000)]

    impls = [("python", _python)]
    if _rust is not None:
        impls.append(("rust", _rust))
    if BASELINE is not None:
        impls.append(("lzstring(PyPI)", BASELINE))

    print(f"{'payload':16s} {'chars':>9s} " + " ".join(f"{n:>16s}" for n, _ in impls))
    for name, text in cases:
        packed = lz.compress_to_base64(text)
        row_c, row_d = [], []
        for impl_name, impl in impls:
            compress = getattr(impl, "compress_to_base64", None) or impl.compressToBase64
            decompress = getattr(impl, "decompress_from_base64", None) or impl.decompressFromBase64
            _, tc = timed(compress, text)
            _, td = timed(decompress, packed)
            row_c.append(f"{tc:15.3f}s")
            row_d.append(f"{td:15.3f}s")
        print(f"{name:16s} {len(text):9d} " + " ".join(row_d) + "   <- decompress")
        print(f"{'':16s} {'':9s} " + " ".join(row_c) + "   <- compress")


if __name__ == "__main__":
    main(sys.argv[1:])
