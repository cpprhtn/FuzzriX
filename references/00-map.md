# FuzzriX navigation map

The skill spine is [SKILL.md](../SKILL.md). Walk the loop; pull in **one leaf per phase**. Don't read the
whole tree.

## The loop → which leaf

| Phase | Leaf | What it gives you |
|---|---|---|
| 0. Gate | [authorization.md](authorization.md) | who/what you may fuzz; mandatory resource & sandbox caps |
| 1–2. Profile & extract | [context-extraction.md](context-extraction.md) | detect stack/build system; find & rank target functions |
| 3a. Harness | [harness-generation.md](harness-generation.md) | per-engine harness patterns (libFuzzer, AFL++, Atheris, cargo-fuzz, Go) |
| 3b. Dockerfile | [dockerfile-generation.md](dockerfile-generation.md) | trusted base images, sanitizer build flags, layering |
| 4. Build & heal | [self-healing.md](self-healing.md) | the bounded compile-error feedback loop |
| 5. Fuzz | [fuzzing-run.md](fuzzing-run.md) | running with caps, seeding corpus, watching coverage |
| 6. Triage & report | [crash-triage.md](crash-triage.md) | minimize, dedup, classify, severity, report shape |

## Signal → jump (skip the loop when you already see it)

| You already see… | Go to |
|---|---|
| a function taking `const uint8_t* data, size_t size` | [harness-generation.md](harness-generation.md) — it's already libFuzzer-shaped |
| `CMakeLists.txt` / `Makefile` | [dockerfile-generation.md](dockerfile-generation.md#cc-cmake) |
| `pyproject.toml` / `setup.py` | [harness-generation.md](harness-generation.md#python-atheris) |
| `Cargo.toml` | [harness-generation.md](harness-generation.md#rust-cargo-fuzz) |
| `go.mod` | [harness-generation.md](harness-generation.md#go-native) |
| a build error in `docker build` output | [self-healing.md](self-healing.md) |
| a crash file in the output dir | [crash-triage.md](crash-triage.md) |

## Helper scripts

| Script | Use |
|---|---|
| [`scripts/scan_targets.py`](../scripts/scan_targets.py) | `python3 scripts/scan_targets.py <repo>` → ranked candidate target functions (JSON) |
| [`scripts/run_fuzz.sh`](../scripts/run_fuzz.sh) | `bash scripts/run_fuzz.sh <build-dir> <out-dir> [seconds]` → docker build + capped run |

## Templates

| Template | Use |
|---|---|
| [`templates/cpp-libfuzzer/`](../templates/cpp-libfuzzer/) | starting Dockerfile + `LLVMFuzzerTestOneInput` harness for C/C++ |
