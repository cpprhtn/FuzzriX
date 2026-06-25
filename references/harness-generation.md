# Harness generation

A harness is the glue that turns "a function" into "a fuzz target": it takes the fuzzer's raw bytes and maps
them onto the target function's arguments, then calls it. Keep it **minimal, deterministic, and crash-only**
(no prints, no network, no global mutation that survives a run).

## Golden rules (all engines)

- **Map bytes → arguments faithfully.** If the function wants `(ptr, len)`, pass exactly that. If it wants
  structured args (an int + a buffer), carve them out of the input deterministically (e.g. first 4 bytes →
  int, rest → buffer) and document the layout.
- **Reset state each call.** `LLVMFuzzerTestOneInput` may be called millions of times in one process. Free
  what you allocate; don't leak; don't depend on call order.
- **No early returns that hide bugs**, but *do* reject inputs too short to be meaningful (`if (size < N)
  return 0;`).
- **Fail loud.** Let the sanitizer catch the crash — don't wrap the target in a try/catch that swallows it.
- **Build a tiny seed corpus** from any sample files in the repo; even one valid input massively speeds
  coverage.

---

## Engine model — what libFuzzer reaches, and what each stack catches

libFuzzer is a **C/C++ engine**: it needs a C-ABI entry (`LLVMFuzzerTestOneInput`) **and** coverage
instrumentation (LLVM SanitizerCoverage, supplied by `-fsanitize=fuzzer`). So *raw* libFuzzer only works for
LLVM-compiled languages; everything else needs a **per-language bridge that reuses the libFuzzer engine** (the
bridge feeds its own coverage into libFuzzer's counters) — or a **separate engine** entirely. "libFuzzer for
any language" is the wrong model; **"libFuzzer engine + a per-language coverage bridge"** is the right one.

| Stack | libFuzzer relation | Driver | Reuses `/fuzzer` path? |
|---|---|---|---|
| **C / C++** | direct (native) | `-fsanitize=fuzzer` | ✅ |
| **Rust** | direct (rustc = LLVM) | `cargo-fuzz` / `libfuzzer-sys` (links real libFuzzer) | ✅ (`cp` the binary) |
| **Swift / Obj-C** | direct (LLVM) | `-fsanitize=fuzzer` | ✅ |
| **Python** | bridge (embeds libFuzzer) | **Atheris** (bytecode-coverage) | ✅ (1-line wrapper) |
| **Java / JVM** | bridge | **Jazzer** | ✅ (libFuzzer-style CLI; see [§ Java/JVM](#jvm-jazzer) + `templates/jvm-jazzer/`) |
| **JS / Node** | bridge | **Jazzer.js** | ◑ (no template yet) |
| **C# / .NET** | bridge | **SharpFuzz** (libFuzzer/AFL) | ◑ (no template yet) |
| **Go** | ❌ not libFuzzer | native `go test -fuzz` | ❌ separate runner |

"Reuses `/fuzzer` path" = accepts the libFuzzer flags `run_fuzz.sh` passes (`-max_total_time`,
`-artifact_prefix`, a corpus dir — see [fuzzing-run.md](fuzzing-run.md)). The libFuzzer family shares it;
**Go is the exception** — drive it directly (see [dockerfile-generation.md](dockerfile-generation.md)).

**What the engine actually catches differs by stack** — this drives both harness design (what to let through vs
catch) and triage ([crash-triage.md](crash-triage.md)):

| Stack | Primary bug classes the engine surfaces |
|---|---|
| **C / C++ / Rust `unsafe`** | memory corruption via **ASan/UBSan** (heap/stack OOB, UAF, double-free, int-overflow), SEGV, OOM, hang |
| **Rust (safe)** | `panic!`/`unwrap` aborts, debug arithmetic overflow, OOM, hang — **not** memory corruption (that's the point of safe Rust) |
| **Python / Java / JS / .NET** (managed) | uncaught exceptions / assertion failures, infinite loops & algorithmic blowup (timeout), OOM — **plus memory bugs in any native C extension they call** (the real prize; ASan applies there) |
| **Go** | `panic`, data races (build with `-race`), OOM, hang |

In a **managed-language** harness, catch only the *expected* exceptions (e.g. a parser's `ValueError`/`KeyError`)
and let everything else crash the run — an *unexpected* exception type, a hang, or a native-extension memory
error is the finding. In **native/`unsafe`** harnesses you don't catch anything: let the sanitizer abort.

---

## C / C++ — libFuzzer (default, MVP)

The entry point. Start from [`templates/cpp-libfuzzer/harness.cc`](../templates/cpp-libfuzzer/harness.cc).

```cpp
#include <cstdint>
#include <cstddef>
#include "target.h"   // declares the function under test

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size < 1) return 0;
    // Simplest case: target already takes (buffer, length)
    parse_thing(data, size);
    return 0;
}
```

**Return value contract.** `LLVMFuzzerTestOneInput` returns `0` to *accept* the input (it may be added to
the corpus) or `-1` to *reject* it (libFuzzer will not add it to the corpus, regardless of the coverage it
triggered). Any value other than `0` and `-1` is reserved for future use — always return one of those two.
`-1` is useful in a parsing harness when you want only inputs that parse successfully to seed the corpus:

```cpp
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (auto *obj = parse_me(data, size)) {
        obj->do_something_interesting();
        return 0;   // accept — may be added to the corpus
    }
    return -1;      // reject — will not be added to the corpus
}
```

Need structured args? Carve deterministically:

```cpp
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size < 5) return 0;
    uint32_t opts; memcpy(&opts, data, 4);
    const uint8_t *body = data + 4;
    size_t body_len = size - 4;
    decode_frame(opts, body, body_len);
    return 0;
}
```

For anything more than one or two fields, prefer **`FuzzedDataProvider`** over hand-rolled `memcpy` slicing —
it ships with the libFuzzer toolchain and derives typed values deterministically from the byte stream:

```cpp
#include <fuzzer/FuzzedDataProvider.h>

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    FuzzedDataProvider fdp(data, size);
    int          mode = fdp.ConsumeIntegralInRange<int>(0, 3);   // bounded enum/flag
    uint32_t     len  = fdp.ConsumeIntegral<uint32_t>();
    std::string  name = fdp.ConsumeRandomLengthString(64);       // stops at len cap or input end
    std::vector<uint8_t> body = fdp.ConsumeRemainingBytes<uint8_t>();
    decode(mode, len, name, body.data(), body.size());
    return 0;
}
```

Rules of thumb: consume **fixed-layout fields first, variable-length last** (`ConsumeRemainingBytes` /
`ConsumeRandomLengthString`), so a one-byte mutation maps to one logical field and the fuzzer can learn the
layout. `FuzzedDataProvider` already no-ops gracefully on short input, so per-field `if (size < N)` guards are
unneeded once you switch to it — but keep a guard for the raw `(data, size)` path above.

**Two ends of the buffer.** `FuzzedDataProvider` reads from both ends: the byte-sequence methods
(`ConsumeBytes*`, `ConsumeBytesAsString`, `ConsumeRandomLengthString`, `ConsumeRemainingBytes*`, `ConsumeData`)
consume from the **front**, while the fixed-width value methods (`ConsumeIntegral*`, `ConsumeFloatingPoint*`,
`ConsumeProbability`, `ConsumeBool`, `ConsumeEnum`, `PickValueInArray`) consume from the **back**. This is
deliberate — it lets the fuzzer mutate buffer *contents* (front) without disturbing the *lengths/selectors* it
encodes (back). The only determinism rule: same input bytes + same sequence of method calls *with the same
arguments* ⇒ same values; change the order, the arguments, or the byte layout and the outputs change. When
input runs out, range/integral/float methods return `min` (≈0 for the unbounded floats), `ConsumeBool` returns
`false`, and byte methods return shorter/empty results (so the harness never faults on short input).

### One-time setup — `LLVMFuzzerInitialize`

`LLVMFuzzerTestOneInput` runs millions of times per process. Do **expensive, idempotent, read-only** setup
(load a config/model file, `setlocale`, register codecs, seed a *fixed* RNG) **once** in the optional
initializer, never per call:

```cpp
extern "C" int LLVMFuzzerInitialize(int *argc, char ***argv) {
    one_time_global_init();   // parse no fuzz input here; same result every process
    return 0;
}
```

Keep it deterministic: no wall-clock seeds, no network, no reading the fuzz input. If a per-call object is
costly to build but safe to reuse read-only, build it here as a `static` and treat it as immutable.

### Determinism & no leaked state (the contract that makes the engine work)

libFuzzer assumes a **pure function of the input**: same bytes → same coverage → same crash. Mutable state
that survives a call breaks the coverage signal and produces flaky, hard-to-dedup crashes. Audit every call
against this table:

| Per-call hazard | Why it hurts the engine | Fix |
|---|---|---|
| `malloc`/`new` without matching free | leaks accumulate; LeakSanitizer floods the log | free before `return 0;`, or use RAII / stack buffers |
| Global/`static` mutated and read next call | coverage depends on call order, not input → flaky crashes | reset to a known state each call, or scope state to the call |
| Open file/socket/global cache left dirty | non-determinism, resource exhaustion, slow units | close/clear per call; do read-only setup in `LLVMFuzzerInitialize` |
| RNG seeded from time/PID | same input crashes only sometimes | seed from a fixed constant (or from `data`) |
| Treating `data` as NUL-terminated | OOB read on every call (a false bug) | copy into a bounded, null-terminated buffer (template Case C) |

Compile (inside the container) with sanitizers + coverage:

```
clang++ -g -O1 -fsanitize=fuzzer,address,undefined harness.cc target.cc -o fuzzer
```

`-fsanitize=fuzzer` is what supplies `main()` and the coverage instrumentation **and** links the
`FuzzedDataProvider` / `LLVMFuzzerTestOneInput` entry — it must be on the **final link** step. If you compile
target TUs separately, instrument them too (`-fsanitize=fuzzer-no-link` on those, `fuzzer` on the link) or the
engine gets no coverage feedback. (Sanitizer build flags and `*_OPTIONS` env live in
[dockerfile-generation.md](dockerfile-generation.md); run flags in [fuzzing-run.md](fuzzing-run.md).)

For C, use `clang` and `extern "C"` isn't needed in the harness if you compile it as C++ but include the C
header with `extern "C" { }` guards (the template handles this).

### Harness smell → engine symptom → fix

The engine's first-run output tells you whether the harness is sound. Read the log before assuming the run was
useful — these symptoms are harness bugs, not target bugs, and feed straight back into the
[self-healing loop](self-healing.md):

| Engine symptom (in stderr) | What the harness did wrong | Fix |
|---|---|---|
| `ERROR: ... Is the code instrumented for coverage?` | target TUs built without `-fsanitize=fuzzer[-no-link]` | instrument the target sources, not just the harness |
| no `#… INITED …` line, non-zero exit | crashes during init / `LLVMFuzzerInitialize` (or undefined entry) | fix init; confirm the entry symbol links |
| `undefined reference to main` at link | `-fsanitize=fuzzer` missing on final link (libFuzzer supplies `main`) | add `-fsanitize=fuzzer` to the link step |
| `undefined reference to LLVMFuzzerTestOneInput` at link | the harness object isn't on the link line | link the harness TU into the final binary |
| `ERROR: LeakSanitizer` on nearly every input | per-call allocation never freed | free per call / reset state (see table above) |
| `exec/s` very low (<100), few `NEW` lines | harness does I/O, heavy allocs, or re-inits per call | move setup to `LLVMFuzzerInitialize`; drop I/O |
| `slow-unit-*` artifacts written | a code path is quadratic on input size | add a sane `if (size > N) return 0;` upper guard |
| crash only on the empty/1-byte seed | missing minimum-size guard | add `if (size < N) return 0;` |

A clean first run shows an `INITED` line, rising `cov:`, and `NEW` lines (see "What to watch" in
[fuzzing-run.md](fuzzing-run.md)).

### AFL++ fallback

If clang/libFuzzer isn't available but AFL++ is, either: reuse the **same** `LLVMFuzzerTestOneInput` and
compile with `afl-clang-fast` + `-fsanitize=fuzzer` (persistent mode), or write a `main()` that reads a file
arg / stdin and calls the target, then run under `afl-fuzz`. Prefer the libFuzzer-entry route — one harness,
both engines. See [dockerfile-generation.md](dockerfile-generation.md#aflplusplus).

---

## Python — Atheris {#python-atheris}

```python
import atheris, sys
with atheris.instrument_imports():
    import mymodule

def TestOneInput(data):
    fdp = atheris.FuzzedDataProvider(data)
    try:
        mymodule.parse(fdp.ConsumeBytes(fdp.remaining_bytes()))
    except (ValueError, KeyError):   # expected, non-bug exceptions
        pass

atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
```

> **Native C extensions are a blind spot.** `atheris.instrument_imports()` instruments *Python bytecode*
> only. If the target is a C extension (e.g. `ujson`, `lxml`, `Pillow`'s `_imaging`), atheris sees it as a
> black box — the corpus barely grows and coverage looks flat even though the run is "working" (validated:
> `ujson` ran millions of execs but the corpus stayed at 1). To actually fuzz native code, build the extension
> with coverage + ASan via `atheris.instrument_func` / `atheris_no_libfuzzer` and a sanitizer-instrumented
> build of the extension (Atheris docs: "Fuzzing Python extensions"). For a pure-Python target this doesn't
> apply. Either way, disclose in the report whether the native layer was actually instrumented.

Catch *expected* exceptions only; let `MemoryError`, `RecursionError`, segfaults, and unexpected types
surface. `FuzzedDataProvider` is the idiomatic way to derive typed inputs.

---

## Java / JVM — Jazzer {#jvm-jazzer}

Jazzer is **libFuzzer for the JVM** (Kotlin/Scala/Clojure too) — same mutation/coverage engine, a JVM agent
supplies the coverage. The harness is a class with a static `fuzzerTestOneInput`:

```java
import com.code_intelligence.jazzer.api.FuzzedDataProvider;

public class YamlFuzzer {
    public static void fuzzerTestOneInput(FuzzedDataProvider data) {
        try {
            new org.yaml.snakeyaml.Yaml().load(data.consumeRemainingAsString());
        } catch (RuntimeException expected) {   // malformed input rejected by design
        }
    }
    // optional one-time setup: public static void fuzzerInitialize() { ... }
}
```

The signature is either `fuzzerTestOneInput(FuzzedDataProvider data)` (typed values; same front/back
consumption model as the C++ FDP) or `fuzzerTestOneInput(byte[] data)`. Compile against the Jazzer API and the
target jar, then drive it the OSS-Fuzz way:

```dockerfile
FROM gcr.io/oss-fuzz-base/base-builder-jvm        # bundles JDK + a working Jazzer
RUN javac -cp "$JAZZER_API_PATH:/target.jar" -d / Fuzzer.java
# /fuzzer = wrapper so run_fuzz.sh's `docker run /fuzzer <libFuzzer flags>` just works:
RUN printf '#!/bin/bash\nexec /usr/local/bin/jazzer_driver \
  --agent_path=/usr/local/bin/jazzer_agent_deploy.jar \
  --cp=/:/target.jar --target_class=Fuzzer --jvm_args="-Xmx2048m:-Xss1024k" "$@"\n' > /fuzzer && chmod +x /fuzzer
```

`jazzer_driver` accepts the same libFuzzer flags `run_fuzz.sh` passes (`-max_total_time`, `-artifact_prefix`,
a corpus dir), so the JVM stack reuses the `/fuzzer` path like Atheris does. **Compile with `javac -encoding
UTF-8`** — the base image's default locale is US-ASCII, so any non-ASCII byte in the source (a comment, a
string literal) fails the build with `unmappable character` (a real self-heal hit). On Apple-silicon/arm64
hosts, pull the x64 base image with `DOCKER_DEFAULT_PLATFORM=linux/amd64` (it runs under emulation).

**What counts as a finding (managed runtime):** an **uncaught exception/`Error`** (so catch only the parser's
*declared* failure mode — usually a `RuntimeException` subtype — and let everything else through: a
`StackOverflowError`, `OutOfMemoryError`, `NullPointerException` from library code, or a timeout is the bug).
Jazzer also ships **bug detectors** that turn silent sinks into crashes — SSRF, OS command injection, path
traversal, deserialization, LDAP/SQL/expression injection — so a reachable injection sink crashes even without a
memory error. `--instrumentation_includes=com.target.**` keeps instrumentation (and detectors) focused on the
target's packages. (Same managed-language triage rule as Python — see the engine-model table above.)

---

## Rust — cargo-fuzz {#rust-cargo-fuzz}

```rust
#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = mycrate::parse(data);
});
```

Scaffold with `cargo fuzz init` + `cargo fuzz add <name>`; the harness lives in `fuzz/fuzz_targets/`. Use
`arbitrary` for structured inputs.

---

## Harness shapes — beyond feed-bytes-to-one-parser {#harness-shapes}

The default shape (raw bytes → one decode call) finds bugs in *parsers*. Heavier
domains — **crypto/TLS, media/codecs, serialization** — usually need a different
*shape* to expose bugs or to get past a self-check. Pick the shape during
threat-modeling, then synthesize it; this is the "differential/stateful axis"
[strategy-selection.md](strategy-selection.md) defers here.

**1. Round-trip (the cheapest oracle).** When a lib both encodes and decodes,
assert the round-trip identity — a mismatch is a bug the parser alone never
signals (silent corruption, not a crash). Canonical for codecs, serializers,
compression, big-int/ASN.1:

```cpp
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    Obj *o = decode(data, size);
    if (!o) return 0;                       // rejecting malformed input is fine
    std::vector<uint8_t> re = encode(o);    // o -> bytes
    Obj *o2 = decode(re.data(), re.size()); // bytes -> o2 ; must succeed + match
    assert(o2 && equal(o, o2));             // ASan/abort flags the divergence
    free_obj(o); free_obj(o2);
    return 0;
}
```

**2. Differential (two implementations, one input).** Feed the *same* bytes to two
independent decoders and compare outputs/return codes; a disagreement is a bug in
one of them. The standard way to fuzz crypto/TLS and format parsers without a spec
oracle (e.g. two X.509 / two JSON / two PNG decoders). Compare *normalized*
outputs (canonical form, sorted), and treat "both reject" / "both accept+equal" as
the only OK states — accept-vs-reject is the finding.

**3. Structure-aware / multi-stage (stateful protocols).** A TLS/SSH/QUIC handshake
or a multi-frame container won't be reached by one flat buffer — the target gates
each step on the previous. Split the input into a *script* of steps with
`FuzzedDataProvider`, driving the state machine:

```cpp
FuzzedDataProvider fdp(data, size);
Conn *c = conn_new();
while (fdp.remaining_bytes() > 0) {
    auto msg = fdp.ConsumeRandomLengthString();      // one protocol record
    if (feed_record(c, msg.data(), msg.size()) != OK) break;
}
conn_free(c);
```

For deeply structured inputs (media containers, protobufs) consider a grammar:
libprotobuf-mutator (`-fsanitize=fuzzer` + `LLVMFuzzerMutate`) mutates a typed
message instead of raw bytes, so every input is structurally valid and the fuzzer
spends its budget on *semantics*, not on re-discovering the format.

**4. Self-check gates (checksum / MAC / signature).** A CRC, length-prefix, HMAC,
or signature check rejects ~every mutation before the interesting code runs (you'll
see `cov` flat in [coverage-iteration.md](coverage-iteration.md)). In order of
preference: ① build with the project's fuzz mode that stubs the check
(`-DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION` is the libFuzzer convention; many libs
have an equivalent), ② recompute the checksum *inside* the harness before calling
the target (parse field, fix CRC, then decode), or ③ if neither is possible, record
it as a **disclosed coverage limit**, not a clean run. Never just leave the fuzzer
stuck behind a MAC and report "no bugs."

**Use the project's own fuzzers when they exist.** OpenSSL (`fuzz/`), ffmpeg
(`tools/target_dec_fuzzer.c`), mbedTLS (`programs/fuzz/`), and most OSS-Fuzz-onboarded
libs ship maintained libFuzzer harnesses already in the shape above — building those
beats hand-writing one. Your job becomes the *build* ([dockerfile-generation.md](dockerfile-generation.md))
+ corpus + triage, not harness authoring.

## Go — native fuzzing {#go-native}

```go
func FuzzParse(f *testing.F) {
    f.Add([]byte("seed"))
    f.Fuzz(func(t *testing.T, data []byte) {
        _ = Parse(data)
    })
}
```

Run with `go test -fuzz=FuzzParse -fuzztime=60s`. No external engine needed.

---

## Output of this phase

A harness file per target, plus a seed corpus dir if any sample inputs exist. Hand off to
[dockerfile-generation.md](dockerfile-generation.md) to build it.
