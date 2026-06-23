# Dockerfile generation

The Dockerfile is the second half of the dual artifact. It pins a **trusted fuzzing base image**, layers the
project source + harness, builds with **sanitizers + coverage**, and produces a runnable fuzzer binary. All
toolchain complexity lives here so the host stays clean (BYOD).

## Principles

- **Start from a trusted base**, don't hand-roll a toolchain: `aflplusplus/aflplusplus` (ships clang +
  AFL++ + sanitizers), an OSS-Fuzz base image, or an official `silkeh/clang` / LLVM image.
- **Pin a tag**, never `:latest` in committed output (reproducibility). For `aflplusplus/aflplusplus` the
  version tags carry a leading **`v`** (`v4.21c`, `v5.00c`) — a bare `4.21c` does not resolve.
- **Build deps first, source last** so Docker layer cache survives source edits during the self-heal loop.
- **Compile with sanitizers**: ASan (memory) + UBSan (undefined behavior) at minimum; libFuzzer for the
  engine. `-g -O1` keeps stacks readable and fuzzing fast.
- **Compile C targets as C**: a `.c` file fed to `clang++` builds in C++ mode and name-mangles its symbols,
  so the harness's `extern "C"` references fail to link ("undefined reference"). Compile the `.c` with
  `clang` (`-fsanitize=fuzzer-no-link,address,undefined -c`), then link the object into the `clang++` harness.
- **Keep the build command in the Dockerfile**, not hidden in a script, so the self-heal loop edits one
  visible place.
- Produce a known binary path **outside `/out`** (e.g. `/fuzzer`) so `run_fuzz.sh` can launch it. `run_fuzz.sh`
  bind-mounts the host out-dir over `/out` at run time, so a binary built into `/out` is masked and the run
  fails with `stat /out/fuzzer: no such file or directory`. Keep `/out` for corpus + crashes only.

---

## C/C++ — CMake or Make {#cc-cmake}

Start from [`templates/cpp-libfuzzer/Dockerfile`](../templates/cpp-libfuzzer/Dockerfile). Minimal libFuzzer
build of a couple of source files:

```dockerfile
FROM aflplusplus/aflplusplus:v4.21c
ENV CC=clang CXX=clang++
WORKDIR /src
COPY . /src
# C++ target: build sources + harness with libFuzzer + ASan + UBSan
RUN clang++ -g -O1 -fsanitize=fuzzer,address,undefined \
        harness.cc src/target.cc \
        -I src -o /fuzzer
# C target: compile the .c as C first (clang, not clang++), then link the object:
#   RUN clang -g -O1 -fsanitize=fuzzer-no-link,address,undefined -I src -c src/target.c -o /target.o
#   RUN clang++ -g -O1 -fsanitize=fuzzer,address,undefined harness.cc /target.o -I src -o /fuzzer
```

For a CMake project, build the library with sanitizer flags, then link the harness against it:

```dockerfile
FROM aflplusplus/aflplusplus:v4.21c
ENV CC=clang CXX=clang++ \
    CFLAGS="-g -O1 -fsanitize=address,undefined -fsanitize=fuzzer-no-link" \
    CXXFLAGS="-g -O1 -fsanitize=address,undefined -fsanitize=fuzzer-no-link"
WORKDIR /src
COPY . /src
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug && cmake --build build -j
RUN clang++ -g -O1 -fsanitize=fuzzer,address,undefined \
        harness.cc -I include -Lbuild -l<yourlib> -o /fuzzer
```

Note `-fsanitize=fuzzer-no-link` on the library (instrument but don't add the entry point) and
`-fsanitize=fuzzer` on the final link (adds `main`).

### aflplusplus {#aflplusplus}

The `aflplusplus/aflplusplus` base also gives you `afl-clang-fast`. To run under AFL++ instead of libFuzzer,
compile the same harness with `afl-clang-fast++ -fsanitize=fuzzer` for persistent mode, or build a
file/stdin `main()` and launch with `afl-fuzz -i <seeds> -o <out> -- ./fuzzer @@`.

---

## Python — Atheris

Start from [`templates/python-atheris/`](../templates/python-atheris/) — it bakes
in the fixes below. Atheris install is **environment-sensitive**; these three
pitfalls each cause a hard build/run failure (all hit during dogfooding):

- **Python 3.11+** — recent atheris uses `dis.Positions`; on 3.10 it dies at
  *import* with `module 'dis' has no attribute 'Positions'`. Use `python:3.11+`,
  not `ubuntu:22.04` (which ships 3.10).
- **compiler-rt fuzzer archive** — `clang` alone (under `--no-install-recommends`)
  omits the libFuzzer `.a`; the wheel build fails with *"Failed to find libFuzzer
  archive"*. Install `libclang-rt-<ver>-dev` too.
- **`CLANG_BIN`** — atheris needs it set to locate that archive, plus `CC/CXX`
  pointed at clang (the minimal image may have no gcc → *"Unsupported compiler"*).

```dockerfile
FROM python:3.11
ENV CC=clang CXX=clang++ CLANG_BIN=clang
RUN apt-get update && apt-get install -y --no-install-recommends \
        clang libclang-rt-19-dev && \
    pip3 install --no-cache-dir atheris && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . /src
# RUN pip3 install -e .          # if the target is a package
# Unify the entry point: run_fuzz.sh launches /fuzzer with libFuzzer flags, and
# an atheris harness IS a libFuzzer driver — a tiny wrapper makes it reusable.
RUN printf '#!/bin/sh\nexec python3 /src/harness.py "$@"\n' > /fuzzer && chmod +x /fuzzer
```

---

## Rust — cargo-fuzz

cargo-fuzz produces a **libFuzzer** binary, so it slots straight into `run_fuzz.sh`
once you copy it to `/fuzzer`. The fuzz crate should declare an independent
`[workspace]` so its build doesn't get absorbed into the target crate's workspace.

```dockerfile
FROM rustlang/rust:nightly
RUN cargo install cargo-fuzz
WORKDIR /src
COPY . /src
RUN cargo fuzz build <target>
# Binary lands in fuzz/target/<triple>/release/<target>; unify the entry point:
RUN cp /src/fuzz/target/*/release/<target> /fuzzer
```

---

## Go — native

Go's `testing.F` fuzzer is **not** a libFuzzer driver — it has its own runner and
flags (`-fuzz`, `-fuzztime`) and does **not** accept the libFuzzer flags
`run_fuzz.sh` passes (`-max_total_time`, `-artifact_prefix`, a corpus dir). So Go
does not drop into the shared `/fuzzer` path; drive it directly instead:

```dockerfile
FROM golang:1.22
WORKDIR /src
COPY . /src
RUN go build ./...
# Run directly (NOT via run_fuzz.sh): go test -fuzz=FuzzParse -fuzztime=60s ./...
# Crashes are written under testdata/fuzz/<FuzzName>/.
```

---

## After building

If `docker build` fails → [self-healing.md](self-healing.md). If it succeeds → run it with caps via
[fuzzing-run.md](fuzzing-run.md) (or `scripts/run_fuzz.sh`).
