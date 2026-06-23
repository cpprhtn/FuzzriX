# Python Atheris template

Starting point for the dual artifact (harness + Dockerfile) on a Python target.
The agent copies these into a `fuzz/` build context, fills in the placeholders,
and drives the build/self-heal/run loop — same as the C/C++ template, same
`run_fuzz.sh`, same `/fuzzer` entry point.

## Files

- [`harness.py`](harness.py) — `atheris.Setup`/`Fuzz` skeleton. Replace
  `TARGET_MODULE` and the byte→argument mapping for the chosen function.
- [`Dockerfile`](Dockerfile) — `python:3.11` base with the atheris-install fixes
  baked in (see notes). Installs a `/fuzzer` wrapper so `run_fuzz.sh` drives it.

## Quick start (agent)

```bash
# 1. pick a build context
mkdir -p fuzz && cp templates/python-atheris/{harness.py,Dockerfile} fuzz/
cp -r <project sources/package needed by the target> fuzz/

# 2. edit fuzz/harness.py (import + call) and, if it's a package, the
#    `pip3 install -e .` line in fuzz/Dockerfile

# 3. build + run with caps (self-heal on failure: read out/build.log, fix, re-run)
bash scripts/run_fuzz.sh fuzz/ out/ 120
```

## Notes

- **Why `python:3.11` (not ubuntu:22.04):** recent atheris uses `dis.Positions`,
  absent in Python 3.10 — it crashes at *import*.
- **Why `libclang-rt-*-dev`:** it ships the libFuzzer `.a` atheris links against;
  `clang` alone under `--no-install-recommends` omits it. Match the version suffix
  to the base image's clang (`python:3.11` → `clang-19` → `libclang-rt-19-dev`).
- **Why `CLANG_BIN`:** atheris uses it to locate that archive; without it the
  wheel build fails with "Failed to find libFuzzer archive".
- **Catch only expected exceptions** in `TestOneInput` — let everything else
  propagate so atheris records it as a crash (an uncaught exception IS the bug).
- The harness runs via `/fuzzer` (a wrapper that execs `python3 harness.py`),
  so the libFuzzer flags `run_fuzz.sh` passes (`-max_total_time`,
  `-artifact_prefix`, corpus dir) work unchanged.
