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
  engine. `-g -O1` keeps stacks readable and fuzzing fast. A compile-time `-fsanitize=` flag is only half
  the story — most need a matching runtime `*_OPTIONS` key baked into the image as `ENV` (table below),
  because the run script launches `/fuzzer` directly and sets no `*_OPTIONS` itself.
- **Compile C targets as C**: a `.c` file fed to `clang++` builds in C++ mode and name-mangles its symbols,
  so the harness's `extern "C"` references fail to link ("undefined reference"). Compile the `.c` with
  `clang` (`-fsanitize=fuzzer-no-link,address,undefined -c`), then link the object into the `clang++` harness.
- **Keep the build command in the Dockerfile**, not hidden in a script, so the self-heal loop edits one
  visible place.
- **Define `FUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION`** (`-DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION`) when the
  target gates fuzzing-unfriendly behavior on it — the canonical libFuzzer macro for disabling CRC/checksum
  checks or seeding a PRNG deterministically (`srand(0)`) so two similar inputs don't fork the corpus. It only
  takes effect if the source `#ifdef`s on it; passing it otherwise is harmless.
- Produce a known binary path **outside `/out`** (e.g. `/fuzzer`) so `run_fuzz.sh` can launch it. `run_fuzz.sh`
  bind-mounts the host out-dir over `/out` at run time, so a binary built into `/out` is masked and the run
  fails with `stat /out/fuzzer: no such file or directory`. Keep `/out` for corpus + crashes only.
- **Narrow the build for huge targets** (ffmpeg, OpenSSL, a browser engine). Building the whole project to
  fuzz one decoder wastes 10–30 min per self-heal round and may OOM the build. Use the project's own knobs to
  compile only the surface under test: ffmpeg `./configure --disable-everything --enable-decoder=<X> --enable-demuxer=<Y>`,
  OpenSSL `./Configure enable-fuzz-libfuzzer no-shared`, mbedTLS its `programs/fuzz` CMake target. Prefer a
  library's **own fuzz build mode** over a from-scratch toolchain — it already wires sanitizers + the harness.
  For codec/media libs, add **`--disable-asm`**: hand-written SIMD (`.S`/NEON/yasm) isn't coverage-instrumented
  anyway, and on arm64 a partial/narrowed build often fails to link with `undefined reference to ff_*_neon` —
  disabling asm forces the instrumented C fallbacks and sidesteps it. (You lose speed, not coverage.)
- **Use the project's maintained harnesses when present** (`fuzz/`, `tools/*_fuzzer.c`, `programs/fuzz/`):
  point the Dockerfile at those instead of hand-authoring, and the build is the only thing left to get right.

## Sanitizer flags & runtime options {#sanitizers}

Each `-fsanitize=` flag you compile with has a runtime twin — an `ASAN_OPTIONS` / `UBSAN_OPTIONS` key that
tunes detection. **Bake the fuzzing-mode defaults into the image as `ENV`.** This is not optional polish: the
FuzzriX runner does a plain `docker run /fuzzer <libFuzzer flags>` and sets **no** `*_OPTIONS` at all (see
[fuzzing-run.md](fuzzing-run.md)), so the only place these take effect is an `ENV` line in the Dockerfile.
Keys are `:`-joined `key=value` pairs.

| Compile flag (build) | Runtime env | Fuzzing-mode keys that matter |
|---|---|---|
| `-fsanitize=fuzzer` (final link, adds `main`) | — | libFuzzer flags live on the command line, not env — see [fuzzing-run.md](fuzzing-run.md) |
| `-fsanitize=fuzzer-no-link` (lib/object, instrument only) | — | combine objects, then one `-fsanitize=fuzzer` link |
| `-fsanitize=address` | `ASAN_OPTIONS` | `detect_leaks=0` (fuzz; flip to `1` for a deep leak pass), `redzone=16` (fast; `128` for analysis), `quarantine_size_mb=0`, `allocator_may_return_null=1`, `detect_stack_use_after_return=1` |
| `-fsanitize=undefined` | `UBSAN_OPTIONS` | `halt_on_error=1` (catch the bug), `print_stacktrace=1`, `silence_unsigned_overflow=1` |
| any of the above | both | the common signal block: `handle_abort=1:handle_segv=1:handle_sigbus=1:handle_sigfpe=1:handle_sigill=1:print_summary=1:use_sigaltstack=1` |

```dockerfile
# ...after the build RUN that produces /fuzzer...
ENV ASAN_OPTIONS=detect_leaks=0:redzone=16:quarantine_size_mb=0:allocator_may_return_null=1:detect_stack_use_after_return=1:alloc_dealloc_mismatch=0:print_scariness=1:fast_unwind_on_fatal=1:print_suppressions=0:handle_abort=1:handle_segv=1:handle_sigbus=1:handle_sigfpe=1:handle_sigill=1:print_summary=1:use_sigaltstack=1
ENV UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1:silence_unsigned_overflow=1:print_suppressions=0:handle_abort=1:handle_segv=1:handle_sigbus=1:handle_sigfpe=1:handle_sigill=1:print_summary=1:use_sigaltstack=1
```

Why these values, not the defaults (the ASan trio is the standard fuzzing-mode reset: `redzone=16`,
`detect_leaks=0`, `quarantine_size_mb=0`):

- **`detect_leaks=0` while fuzzing.** libFuzzer defaults to `detect_leaks=1` (when LSan is available): it
  counts `malloc`/`free` on *every mutation* and escalates to a full LeakSanitizer pass on a count mismatch.
  That per-mutation accounting tanks `exec/s` and buries real memory-safety crashes under leak noise, so turn
  it off while fuzzing. Run one deep pass with `detect_leaks=1` only if leaks are the goal.
- **`redzone=16`** is the fast fuzzing redzone; `32` is typical for corpus pruning and `128` for a
  crash-analysis re-run (catches subtler overflows, slower). Note a large redzone (cutoff around `64`)
  suppresses OOM/hang reporting, so keep it small while fuzzing. Never `redzone=0` — that disables
  redzone-based overflow detection entirely.
- **`quarantine_size_mb=0`** keeps freed memory from piling up and OOM-killing the capped container; a
  nonzero quarantine improves use-after-free detection but costs RAM you don't have under `--memory`.
- **`allocator_may_return_null=1`** turns a huge-allocation request into a `NULL` return instead of an
  instant abort, so a giant-length input is fuzzing signal, not a spurious crash.
- **`halt_on_error=1`** is what makes UBSan *crash* on undefined behavior instead of logging and continuing —
  required for the engine to register the bug. (The crash-reproduce path can instead disable UBSan with
  `halt_on_error=0` to walk past known UB; that's a runtime/triage concern, not something to bake here — see
  [crash-triage.md](crash-triage.md).)
- **`symbolize`** is left at its default; on Linux the sanitizer symbolizes offline. If you want inline
  symbolized frames, the base image must ship `llvm-symbolizer` and you add
  `symbolize=1:external_symbolizer_path=/usr/bin/llvm-symbolizer`.

For TSan (`-fsanitize=thread`) builds, bake `TSAN_OPTIONS=history_size=3:...` (low `history_size` to fit the
memory cap) plus the common signal block; MSan (`-fsanitize=memory`) needs only `MSAN_OPTIONS=symbolize=0:` +
the common signal block. Don't combine `address` with `memory` or `thread` in one binary — they're mutually
exclusive instrumentations.

## Dictionary placement {#dict-options}

A token **dictionary** (`.dict`: magic bytes, keywords, format markers) dramatically helps structured formats
(JSON, protocols, image headers). `COPY` it into the image at a known path next to the binary, e.g.
`/fuzzer.dict`.

- **Format.** One entry per line, value double-quoted, optional label — `kw_png="\x89PNG"` or just `"{}"`.
  Lines starting with `#` are comments. A malformed entry (missing quotes) makes libFuzzer exit with a
  `ParseDictionaryFile: error in line N`, aborting the run rather than fuzzing without it — so keep it clean
  and validate the file exists before wiring it in.

- **Escape every non-printable byte as `\xNN`.** The *only* valid escapes in a dict value are `\\`, `\"`, and
  `\xNN`. A raw control byte — `\r`, `\n`, a literal high byte — makes libFuzzer reject the **whole file**
  (`ParseDictionaryFile: error in line N`), so the run silently loses the dict. This bites image/binary magics
  most: write a PNG magic as `png="\x89PNG\x0d\x0a\x1a\x0a"`, **not** `"\x89PNG\r\n\x1a\n"`. When mining magics
  from source, encode any byte outside `0x20–0x7e` as `\xNN`.

- **A baked `.dict` is not auto-loaded — you must pass `-dict=`.** Raw libFuzzer (which is what `/fuzzer` is,
  launched directly) does *not* pick up a sidecar `<binary>.dict` by convention; the `<binary>.dict`
  auto-discovery you may have seen is a higher-level orchestrator behavior, not something the single
  container does. Wire the dict explicitly:
  - Manual run: `docker run ... /fuzzer -dict=/fuzzer.dict ... /out/corpus`.
  - Via `run_fuzz.sh`: pass `--dict <path-in-build-context>`; the script copies it into the out-dir and
    passes `-dict=/out/<basename>` (it does **not** read `/fuzzer.dict`). See [fuzzing-run.md](fuzzing-run.md).

```dockerfile
# Bake the dictionary next to /fuzzer (still must be passed via -dict= at run time):
COPY target.dict /fuzzer.dict
```

> Note: an INI `.options` file (`[libfuzzer]`/`[asan]`/`[ubsan]` sections) is an **orchestrator** convention
> parsed by a separate Python engine launcher — the FuzzriX single-container runner does not read it, so
> baking one has no effect. Put libFuzzer flags on the run command ([fuzzing-run.md](fuzzing-run.md)) and
> sanitizer options in the `ENV` lines above instead.

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

> **`./configure` (autotools: ffmpeg, OpenSSL, …) — sanitizer flags go in *both*
> cflags and ldflags (common self-heal).** A configure script probes the toolchain
> by *compiling and linking* a tiny test program. If you pass `-fsanitize=address`
> (or `fuzzer-no-link`) only in `--extra-cflags`, the test object compiles with ASan
> but the link step has no ASan runtime → undefined symbols → configure aborts with
> **"C compiler is unable to create an executable file. C compiler test failed."**
> The flags are correct; they're just not on the link line. Fix by mirroring them
> into the link flags too:
> ```dockerfile
> RUN ./configure --cc=clang --disable-everything --enable-decoder=mjpeg \
>         --extra-cflags="-g -O1 -fsanitize=fuzzer-no-link,address,undefined" \
>         --extra-ldflags="-fsanitize=fuzzer-no-link,address,undefined" \
>     && make -j"$(nproc)"
> ```
> (Same root cause for any `CFLAGS`-without-`LDFLAGS` autotools build. CMake's
> `CMAKE_C_FLAGS` feeds both compile and link, so it doesn't hit this.)

> **Generated headers (common self-heal).** Many CMake projects *generate* a header at configure time —
> most often an export header (`<name>_export.h` from `GenerateExportHeader`, defining `<NAME>_EXPORT` etc.).
> If you compile the sources directly (no CMake), the build dies with `fatal error: '<name>_export.h' file
> not found`. Self-heal by writing a minimal stub next to the sources:
> ```c
> #ifndef NAME_EXPORT_H
> #define NAME_EXPORT_H
> #define NAME_EXPORT
> #define NAME_NO_EXPORT
> #endif
> ```
> (Validated on `miniz`, which generates `miniz_export.h`.) The general rule: a "file not found" on a header
> that isn't in the repo usually means it's CMake-generated — stub it, or run the project's `cmake` configure
> step to produce it.

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