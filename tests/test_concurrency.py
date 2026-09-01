"""The extension must let go of the interpreter while it works.

Not a performance nicety. The service this was written for awaits its unpacking inline in a
request handler, and the cheap remedy for that is to run the call in a thread — which does
nothing whatsoever if the extension holds the GIL for the whole call: the worker thread
holds the interpreter and every other request waits exactly as before.

Both tests calibrate themselves against the machine they run on, by comparing the turns a
neighbouring thread gets during the call with the turns it gets while ordinary Python code
runs for the same time. Two earlier versions did not, and both failed somewhere the property
held perfectly well: one counted turns against a fixed threshold and fell over in a
container where the payload decoded in half a millisecond, the other compared wall-clock
time for one call against two and fell over on a two-core runner. Elapsed time measures the
scheduler; turns measure whether the interpreter was available, which is the actual claim.
"""

from __future__ import annotations

import random
import threading
import time

import lz_string as lz


def _payload() -> tuple[str, str]:
    """Something big enough to take real time to decode on any machine."""
    rng = random.Random(20260901)
    block = "".join(rng.choice('abcdefgh0123456789{}":,') for _ in range(20_000))
    text = block * 100  # two million characters out, whatever the machine
    return text, lz.compress_to_base64(text)


TEXT, PAYLOAD = _payload()


def _count_turns(during) -> int:
    """Turns a plain Python thread gets while `during()` runs."""
    turns = 0
    stop = threading.Event()

    def spin() -> None:
        nonlocal turns
        while not stop.is_set():
            turns += 1
            time.sleep(0)

    worker = threading.Thread(target=spin)
    worker.start()
    try:
        during()
    finally:
        stop.set()
        worker.join()
    return turns


def _turns_against(work) -> tuple[int, int]:
    """Turns a spinning thread gets while `work()` runs, and while Python runs as long."""
    during = _count_turns(work)

    elapsed = time.perf_counter()
    _count_turns(work)
    elapsed = time.perf_counter() - elapsed

    def busy() -> None:
        until = time.perf_counter() + elapsed
        while time.perf_counter() < until:
            pass

    return during, _count_turns(busy)


def test_the_interpreter_stays_available_during_a_decompress() -> None:
    during_call, against_python = _turns_against(lambda: lz.decompress_from_base64(PAYLOAD))
    assert during_call >= against_python * 0.5, (
        f"the neighbour got {during_call} turns while the extension ran and "
        f"{against_python} against ordinary Python code — the GIL is being held"
    )


def test_the_interpreter_stays_available_during_a_compress() -> None:
    # Compression is the longer of the two, so this is where holding the GIL would hurt most.
    during_call, against_python = _turns_against(lambda: lz.compress_to_base64(TEXT))
    assert during_call >= against_python * 0.5, (
        f"the neighbour got {during_call} turns while the extension ran and "
        f"{against_python} against ordinary Python code — the GIL is being held"
    )
