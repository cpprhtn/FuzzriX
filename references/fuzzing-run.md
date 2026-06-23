# Fuzzing run

The image builds. Now run the fuzzer **with caps**, mount an output dir for corpus + crashes, and watch for
crashes / coverage plateau. Default to a short run; let the user opt into longer.

## Run it (libFuzzer, the MVP path)

`scripts/run_fuzz.sh` wraps this, but the shape is:

```bash
mkdir -p out/corpus out/crashes
# --name (not --rm): keep the container visible in `docker ps -a` after it exits.
docker run --name fuzzrix-<target>-run \
  --memory=2g --cpus=2 --pids-limit=512 --network=none \
  -v "$PWD/out:/out" \
  fuzzrix-<target> \
  /fuzzer \
    -max_total_time=120 \
    -rss_limit_mb=2048 \
    -timeout=25 \
    -artifact_prefix=/out/crashes/ \
    /out/corpus
```

**One entry point, every engine.** `run_fuzz.sh` always launches `/fuzzer`. C/C++
build the binary there directly; Python (atheris) and Rust (cargo-fuzz) are also
libFuzzer drivers, so a one-line `/fuzzer` wrapper (atheris) or `cp` (cargo-fuzz)
lets them reuse this exact path with the same flags. Go is the exception — its
native fuzzer is a separate runner, drive it directly (see dockerfile-generation.md).

Key flags:

- `-max_total_time=<s>` — wall-clock cap (the most important one).
- `-rss_limit_mb` — kill if memory balloons; pairs with `--memory`.
- `-timeout=<s>` — flag a single input that takes too long (hang/inf-loop bug).
- `-artifact_prefix=/out/crashes/` — where crashing inputs (`crash-*`, `oom-*`, `timeout-*`) are written.
- last arg = corpus dir — libFuzzer reads existing seeds and writes new interesting inputs back.
- `-jobs=<n> -workers=<n>` — parallel runs (deep mode).
- `-dict=<file>` — a token dictionary (magic bytes, keywords) dramatically helps structured formats.

## Seed the corpus

Before running, copy any sample/valid inputs you found (`test/`, `samples/`, `corpus/`, example files) into
`out/corpus`. One valid input often unlocks orders of magnitude more coverage than starting from empty.

## What to watch in the output

- `cov:` — coverage (edges hit). Rising = good; flat for a long time = plateau (stop, or add seeds/dict).
- `exec/s` — throughput. Very low (<100/s) usually means the harness does too much per call (I/O, allocs).
- `NEW` lines — corpus is growing, fuzzer is exploring.
- A `==ERROR==` / `SUMMARY: AddressSanitizer:` block, then `Test unit written to /out/crashes/crash-...` —
  **you found a crash.** Note the file, let the run finish (or stop), go to triage.

## Engine variations

- **AFL++**: `afl-fuzz -i out/corpus -o out/findings -- /fuzzer @@` (file input) — crashes land in
  `out/findings/default/crashes/`. Set `AFL_..` env and `-V <seconds>` for a time cap.
- **Atheris**: `python3 harness.py -max_total_time=120 out/corpus` — same libFuzzer flags.
- **cargo-fuzz**: `cargo fuzz run <name> -- -max_total_time=120` — crashes in `fuzz/artifacts/<name>/`.
- **Go**: `go test -fuzz=FuzzX -fuzztime=120s` — failing inputs in `testdata/fuzz/FuzzX/`.

## Stop conditions

Stop when: time cap hits, a crash is found (in quick mode), coverage plateaus for a long stretch, or the user
says so. Then collect the crash artifacts and go to [crash-triage.md](crash-triage.md).
