# C/C++ libFuzzer template

Starting point for the dual artifact (harness + Dockerfile) on a C/C++ target. The agent copies these into
a `fuzz/` build context, fills in the placeholders, and drives the build/self-heal/run loop.

## Files

- [`harness.cc`](harness.cc) — `LLVMFuzzerTestOneInput` skeleton. Replace `TARGET_HEADER.h` and the
  byte→argument mapping for the chosen target function.
- [`Dockerfile`](Dockerfile) — `aflplusplus/aflplusplus` base (clang + AFL++ + sanitizers). Edit the build
  `RUN` line to match the project's sources / includes / deps.

## Quick start (agent)

```bash
# 1. pick a build context
mkdir -p fuzz && cp templates/cpp-libfuzzer/{harness.cc,Dockerfile} fuzz/
cp -r <project sources needed by the target> fuzz/src/

# 2. edit fuzz/harness.cc  (header + call) and fuzz/Dockerfile (sources/-I/-l)

# 3. build + run with caps (self-heal on build failure: read fuzz/../out/build.log, fix, re-run)
bash scripts/run_fuzz.sh fuzz/ out/ 120
```

## Notes

- Placeholders to replace: `TARGET_HEADER.h` in the harness; `src/TARGET.cc` + `-I src` in the Dockerfile.
- C target? Wrap its header in `extern "C" { ... }` in the harness, AND compile the `.c` with `clang` (not
  `clang++`) — clang++ builds a `.c` in C++ mode and mangles the symbols, breaking the `extern "C"` link.
- Sanitizers (`address,undefined`) are on by default — don't drop them to force a build; that defeats the
  purpose. Fix the actual error instead (see [self-healing.md](../../references/self-healing.md)).
- The fuzzer binary is produced at `/fuzzer` inside the image (NOT `/out/fuzzer` — `run_fuzz.sh` bind-mounts
  the host out-dir over `/out`, which would mask it); `run_fuzz.sh` launches it.
