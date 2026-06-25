# Self-healing build loop

The core technical bet of FuzzriX: an LLM-written harness/Dockerfile rarely compiles first try, so **you read
the build error and fix it yourself**, in a bounded loop. This is your inner loop — keep it tight so one
stubborn target doesn't eat the session.

## The loop

```
round = 0
build:
  docker build -t fuzzrix-<target> <build-dir>  2> build.log
  if success: done → go fuzz
  round += 1
  if round > MAX (default 3): record failure in ledger with the last error → next target
  read build.log → diagnose → edit harness.cc OR Dockerfile → goto build
```

Always capture stderr: `docker build ... 2>&1 | tee build.log`. Read the **first** error, not the cascade of
follow-ons — fixing the first often clears the rest.

## Diagnose → fix (common C/C++ failures)

| Error signature | Likely cause | Fix |
|---|---|---|
| `fatal error: 'x.h' file not found` | missing include path | add `-I<dir>` to the compile line, or `COPY` the header |
| `undefined reference to 'foo'` | source/lib not linked | add the missing `.c/.cc` to the compile cmd, or `-L`/`-l` the lib |
| `unknown type name` / `was not declared` | wrong/missing header, or C vs C++ linkage | include the right header; wrap C headers in `extern "C" { }` |
| `too few/many arguments to function` | harness calls target with wrong signature | re-read the real signature, fix the byte→arg mapping |
| `cannot find -lXXX` | dependency not installed in image | `apt-get install` it in the Dockerfile, or build it |
| CMake `Could NOT find <Pkg>` | missing build dependency | install the `-dev` package in the Dockerfile |
| `clang: command not found` | base image lacks toolchain | switch base to `aflplusplus/aflplusplus` or an LLVM image |
| `./configure`: **"C compiler is unable to create an executable / C compiler test failed"** | sanitizer flags in `--extra-cflags` but not `--extra-ldflags`: configure's link probe lacks the ASan runtime | mirror the flags into `--extra-ldflags` (autotools — ffmpeg/OpenSSL; see [dockerfile-generation.md](dockerfile-generation.md#cc-cmake)) |
| build hangs / OOM | building the whole project | scope the build to just the target's translation units, or narrow configure (`--disable-everything --enable-decoder=X`) |

## Diagnose → fix (runtime / link-time, surfaces on first run)

| Symptom | Cause | Fix |
|---|---|---|
| `LLVMFuzzerTestOneInput` undefined | linked without `-fsanitize=fuzzer` on final step | add it to the final link |
| immediate crash on empty input | harness derefs without length check | add `if (size < N) return 0;` |
| "infinite" leak reports | harness leaks each call | free allocations; reset state per call |
| ASan: `requires dynamic ...` / container abort | missing ASan runtime or `ASAN_OPTIONS` | ensure sanitizer in base image; set options at run |

## Discipline

- **One change per round**, then rebuild — don't shotgun five fixes and lose the signal.
- **Prefer fixing the Dockerfile/compile line over mangling the harness** when the error is environmental
  (missing dep/include) — keep the harness faithful to the target.
- **Never fake success.** If you hit MAX rounds, write the target's verdict as `build-failed` with the last
  error in the ledger and move on. A disclosed gap beats a fabricated pass.
- **Don't loosen safety to make it build** (e.g. dropping sanitizers). A fuzzer without ASan finds far fewer
  bugs — that's defeating the purpose.

When it builds → [fuzzing-run.md](fuzzing-run.md).
