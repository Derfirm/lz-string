"""The extension must let go of the interpreter while it works.

Not a performance nicety. The service this was written for awaits its unpacking inline in a
request handler, and the cheap remedy for that is to run the call in a thread — which does
nothing whatsoever if the extension holds the GIL for the whole call: the worker thread
holds the interpreter and every other request waits exactly as before.

Both tests here calibrate themselves against the machine they run on. An earlier version
counted turns against a fixed threshold and passed on a laptop while failing in a container,
where the same payload decoded in half a millisecond — a test that measures the machine
rather than the code.
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


def test_the_interpreter_stays_available_during_a_decompress() -> None:
    elapsed = time.perf_counter()
    turns_during_call = _count_turns(lambda: lz.decompress_from_base64(PAYLOAD))
    elapsed = time.perf_counter() - elapsed

    # The same wall time spent in Python instead: the neighbour then competes for the GIL
    # rather than having it, so this is the floor a released GIL has to clear.
    def busy() -> None:
        until = time.perf_counter() + elapsed
        while time.perf_counter() < until:
            pass

    turns_against_python = _count_turns(busy)

    assert turns_during_call >= turns_against_python * 0.5, (
        f"the neighbour got {turns_during_call} turns while the extension ran and "
        f"{turns_against_python} against ordinary Python code — the GIL is being held"
    )


def _time(work) -> float:
    start = time.perf_counter()
    work()
    return time.perf_counter() - start


def _both_at_once() -> None:
    threads = [threading.Thread(target=lambda: lz.compress_to_base64(TEXT)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def test_two_compressions_overlap() -> None:
    # Best of three, because scheduling noise only ever makes a run slower: if the calls
    # overlap at all, one of three attempts will show it, and if the GIL is held none will.
    # A single attempt failed on a busy container while the property held perfectly well.
    alone = min(_time(lambda: lz.compress_to_base64(TEXT)) for _ in range(3))
    together = min(_time(_both_at_once) for _ in range(3))

    assert together < alone * 1.7, f"two calls took {together:.2f}s against {alone:.2f}s for one"
