#!/usr/bin/env python3
"""FuzzriX Atheris harness template (Python).

The agent fills in: the import of the target module, and the call that maps the
fuzzer's raw bytes onto the target function. Keep it minimal and deterministic —
no prints, no I/O, no state that survives between calls. See
references/harness-generation.md.

Run (inside the container, via the /fuzzer wrapper the Dockerfile installs):
    python3 harness.py -max_total_time=120 /out/corpus
"""
import sys

import atheris

# Instrument the target on import so atheris gets coverage feedback. Import the
# module(s) under test INSIDE this block.
with atheris.instrument_imports():
    import TARGET_MODULE  # <-- agent: replace with the target module


def TestOneInput(data: bytes):
    # --- agent: map bytes -> target arguments and call it -------------------
    # Case A — target already takes raw bytes:
    #     TARGET_MODULE.parse(data)
    #
    # Case B — target wants structured args; carve them with FuzzedDataProvider:
    #     fdp = atheris.FuzzedDataProvider(data)
    #     n = fdp.ConsumeIntInRange(0, 64)
    #     rest = fdp.ConsumeBytes(n)
    #     TARGET_MODULE.decode(n, rest)
    #
    # Case C — target wants text:
    #     TARGET_MODULE.handle(data.decode("utf-8", "replace"))
    #
    # Catch ONLY the exceptions the target documents as expected input errors —
    # let everything else propagate so atheris records it as a crash:
    #     try:
    #         TARGET_MODULE.parse(data)
    #     except (ValueError, KeyError):
    #         pass
    # ------------------------------------------------------------------------
    TARGET_MODULE.parse(data)  # <-- agent: replace


def main():
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
