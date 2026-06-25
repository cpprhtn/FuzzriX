# FuzzriX navigation map

The skill spine is [SKILL.md](../SKILL.md). Walk the loop; pull in **one leaf per phase**. Don't read the
whole tree.

## The loop → which leaf

| Phase | Leaf | What it gives you |
|---|---|---|
| 0. Gate | [authorization.md](authorization.md) | who/what you may fuzz; mandatory resource & sandbox caps |
| 1–2. Profile & extract | [context-extraction.md](context-extraction.md) | detect stack/build system; find & rank target functions |
| 2b. Strategy | [strategy-selection.md](strategy-selection.md) | pick libFuzzer knobs (value_profile, dict, fork, max_len) per mode + emit rationale |
| 3a. Harness | [harness-generation.md](harness-generation.md) | per-engine harness patterns (libFuzzer, AFL++, Atheris, cargo-fuzz, Jazzer, Go) |
| 3b. Dockerfile | [dockerfile-generation.md](dockerfile-generation.md) | trusted base images, sanitizer build flags + runtime `*_OPTIONS`, dict placement, layering |
| 4. Build & heal | [self-healing.md](self-healing.md) | the bounded compile-error feedback loop |
| 5. Fuzz | [fuzzing-run.md](fuzzing-run.md) | running with caps, flags, exit codes, stderr signals, metrics |
| 5b. Corpus | [corpus-management.md](corpus-management.md) | seed, `-merge=1` minimize, persist & reuse across runs |
| 5c. Coverage loop | [coverage-iteration.md](coverage-iteration.md) | bounded run→diagnose-wall→fix-harness/seed/dict→re-run; the top perf lever |
| 6. Triage & report | [crash-triage.md](crash-triage.md) | minimize/cleanse, dedup signature, security & severity rules, report shape |

## Signal → jump (skip the loop when you already see it)

| You already see… | Go to |
|---|---|
| a function taking `const uint8_t* data, size_t size` | [harness-generation.md](harness-generation.md) — it's already libFuzzer-shaped |
| `CMakeLists.txt` / `Makefile` | [dockerfile-generation.md](dockerfile-generation.md#cc-cmake) |
| `pyproject.toml` / `setup.py` | [harness-generation.md](harness-generation.md#python-atheris) |
| `Cargo.toml` | [harness-generation.md](harness-generation.md#rust-cargo-fuzz) |
| `go.mod` | [harness-generation.md](harness-generation.md#go-native) |
| `pom.xml` / `build.gradle` (Java/Kotlin/Scala) | [harness-generation.md](harness-generation.md#jvm-jazzer) — Jazzer |
| a build error in `docker build` output | [self-healing.md](self-healing.md) |
| a target full of `memcmp`/magic-number checks, or a known file format | [strategy-selection.md](strategy-selection.md) — value_profile + a dict |
| an existing `corpus/` / sample-input dir, or you want runs to accumulate | [corpus-management.md](corpus-management.md) |
| `cov:` flat / a low fraction of edges reached / functions never entered | [coverage-iteration.md](coverage-iteration.md) |
| a crash file in the output dir | [crash-triage.md](crash-triage.md) |

## Helper scripts

| Script | Use |
|---|---|
| [`scripts/scan_targets.py`](../scripts/scan_targets.py) | `python3 scripts/scan_targets.py <repo>` → ranked candidate target functions (JSON) |
| [`scripts/mine_dict.py`](../scripts/mine_dict.py) | `python3 scripts/mine_dict.py <repo> -o fuzz.dict` → libFuzzer dict of magics/keywords mined from source (gets past format gates — see [strategy-selection.md](strategy-selection.md)) |
| [`scripts/run_fuzz.sh`](../scripts/run_fuzz.sh) | `bash scripts/run_fuzz.sh <build-dir> <out-dir> [seconds]` → docker build + capped run |
| [`scripts/cover_gaps.py`](../scripts/cover_gaps.py) | `… /fuzzer -print_coverage=1 \| python3 scripts/cover_gaps.py - --src /src` → ranks frontier / unreached functions to drive the coverage loop ([coverage-iteration.md](coverage-iteration.md)) |

## Templates

| Template | Use |
|---|---|
| [`templates/cpp-libfuzzer/`](../templates/cpp-libfuzzer/) | starting Dockerfile + `LLVMFuzzerTestOneInput` harness for C/C++ |
| [`templates/python-atheris/`](../templates/python-atheris/) | starting Dockerfile + `atheris` harness for Python |
| [`templates/jvm-jazzer/`](../templates/jvm-jazzer/) | starting Dockerfile + Jazzer `fuzzerTestOneInput` harness for Java/JVM |
