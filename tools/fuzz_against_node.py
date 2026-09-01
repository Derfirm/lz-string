"""Differential fuzzing against the reference implementation, running in node.

SPEC.md claims agreement with JavaScript on far more than the golden corpus: thousands of
generated inputs, and thousands of malformed payloads where the two implementations here
must also agree with each other. This is the harness those claims come from, so that they
can be re-run rather than believed.

    npm --prefix tools ci                  # once
    uv run python tools/fuzz_against_node.py                 # 2000 inputs, 4000 junk probes
    uv run python tools/fuzz_against_node.py --inputs 20000  # longer sweep
    uv run python tools/fuzz_against_node.py --seed 7        # a different draw
    uv run python tools/fuzz_against_node.py FILE...         # real payloads, if you have any

The golden corpus in tests/ is a fixed sample of this, small enough to live in git and be
run by every test. This goes wider, needs node, and is not part of the suite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import lz_string as lz
from lz_string import _reference

IMPLEMENTATIONS = (("shipped", lz), ("reference", _reference))
TRANSPORTS = {
    "base64": ("compress_to_base64", "decompress_from_base64"),
    "uri": ("compress_to_encoded_uri_component", "decompress_from_encoded_uri_component"),
    "utf16": ("compress_to_utf16", "decompress_from_utf16"),
    "raw": ("compress", "decompress"),
}


def digest(text: str) -> str:
    # Over the UTF-16LE form: the value need not be valid UTF-8, which is the whole point.
    return hashlib.sha256(text.encode("utf-16-le", "surrogatepass")).hexdigest()[:16]


def ask_node(mode: str, arguments: list[str]) -> list[dict]:
    result = subprocess.run(
        ["node", str(ROOT / "tools" / "differential.mjs"), mode, *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return [json.loads(line) for line in result.stdout.splitlines()]


def generate(rng: random.Random) -> str:
    """Inputs nobody thought to write down, weighted towards the awkward."""
    kind = rng.randrange(8)
    length = rng.randrange(0, 300)
    if kind == 0:  # any code unit at all, surrogates included
        return "".join(chr(rng.randrange(0x10000)) for _ in range(length))
    if kind == 1:  # astral characters: one Python character, two JavaScript ones
        return "".join(chr(rng.randrange(0x110000)) for _ in range(length // 4))
    if kind == 2:
        return "".join(rng.choice('ab{}":,0') for _ in range(length * 3))
    if kind == 3:  # nothing but surrogate halves
        return chr(rng.randrange(0xD800, 0xE000)) * (1 + length % 7)
    if kind == 4:
        return (rng.choice(["ab", "xyz", '{"a":1}']) * (1 + length))[:4000]
    if kind == 5:
        return "".join(chr(rng.randrange(0x80)) for _ in range(length))
    if kind == 6:
        return "".join(chr(rng.choice([0xFFFF, 0xFFFE, 0xD800, 0xDFFF, 0x20])) for _ in range(length))
    return "".join(chr(rng.randrange(0x4E00, 0x9FFF)) for _ in range(length))


def damage(rng: random.Random, good: str) -> str:
    """Payloads broken the ways real ones are: truncated, mutated, polluted."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
    kind = rng.randrange(7)
    if kind == 0:
        return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 200)))
    if kind == 1:
        at = rng.randrange(len(good))
        return good[:at] + rng.choice(alphabet) + good[at + 1 :]
    if kind == 2:
        return good[: rng.randrange(len(good))]
    if kind == 3:
        at = rng.randrange(len(good))
        return good[:at] + rng.choice("!@# \n\t") + good[at:]
    if kind == 4:
        return "".join(chr(rng.randrange(0x10000)) for _ in range(rng.randrange(0, 80)))
    if kind == 5:
        return rng.choice(alphabet) * rng.randrange(1, 300)
    return good + "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 50)))


def check_generated(count: int, seed: int) -> int:
    rng = random.Random(seed)
    inputs = [generate(rng) for _ in range(count)]
    payload_file = ROOT / "tools" / ".fuzz_inputs.jsonl"
    payload_file.write_text(
        "\n".join(json.dumps({"id": i, "input": s}) for i, s in enumerate(inputs)) + "\n",
        encoding="utf-8",
    )
    try:
        oracle = ask_node("inputs", [str(payload_file)])
    finally:
        payload_file.unlink(missing_ok=True)

    failures = 0
    for name, module in IMPLEMENTATIONS:
        wrong = 0
        for row in oracle:
            text = inputs[row["id"]]
            for transport, (compress, _) in TRANSPORTS.items():
                if digest(getattr(module, compress)(text)) != row[transport]:
                    wrong += 1
                    if wrong < 4:
                        print(f"  [{name}] {transport} differs on #{row['id']} ({len(text)} chars)")
        print(f"  [{name:9s}] {count} inputs x {len(TRANSPORTS)} transports: {wrong} differ from node")
        failures += wrong
    return failures


def check_damaged(count: int, seed: int) -> int:
    rng = random.Random(seed)
    good = lz.compress_to_base64('{"party":{"_gold":8536},"switches":[true,false]}' * 20)
    failures = 0
    raised = 0
    disagreed = 0
    for _ in range(count):
        payload = damage(rng, good)
        for _, decompress in TRANSPORTS.values():
            answers = []
            for name, module in IMPLEMENTATIONS:
                try:
                    answers.append(getattr(module, decompress)(payload))
                except BaseException as error:  # noqa: BLE001 - a pyo3 panic is not an Exception
                    raised += 1
                    answers.append(f"RAISED {type(error).__name__} in {name}")
            if answers[0] != answers[1]:
                disagreed += 1
    print(f"  {count} damaged payloads x {len(TRANSPORTS)} functions: {raised} raised, {disagreed} disagreed")
    return failures + raised + disagreed


def check_files(paths: list[str]) -> int:
    oracle = {row["path"]: row for row in ask_node("files", paths)}
    failures = 0
    for name, module in IMPLEMENTATIONS:
        decoded = recompressed = 0
        for path in paths:
            text = module.decompress_from_base64(Path(path).read_text(errors="surrogatepass"))
            if text is None or digest(text) != oracle[path]["decompressed"]:
                failures += 1
                print(f"  [{name}] decompressed differently: {Path(path).name}")
                continue
            decoded += 1
            if digest(module.compress_to_base64(text)) == oracle[path]["recompressed"]:
                recompressed += 1
            else:
                failures += 1
                print(f"  [{name}] recompressed differently: {Path(path).name}")
        print(f"  [{name:9s}] {decoded}/{len(paths)} decoded, {recompressed}/{len(paths)} recompressed")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="base64 lz-string payloads to check as well")
    parser.add_argument("--inputs", type=int, default=2000)
    parser.add_argument("--junk", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=20260901)
    args = parser.parse_args()

    failures = 0
    if args.files:
        print("real payloads, against node:")
        failures += check_files(args.files)
    print("generated inputs, against node:")
    failures += check_generated(args.inputs, args.seed)
    print("damaged payloads, the two implementations against each other:")
    failures += check_damaged(args.junk, args.seed)

    print("clean" if not failures else f"{failures} FAILURES")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
