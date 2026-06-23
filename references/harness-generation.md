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

Compile (inside the container) with sanitizers + coverage:

```
clang++ -g -O1 -fsanitize=fuzzer,address,undefined harness.cc target.cc -o fuzzer
```

For C, use `clang` and `extern "C"` isn't needed in the harness if you compile it as C++ but include the C
header with `extern "C" { }` guards (the template handles this).

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

Catch *expected* exceptions only; let `MemoryError`, `RecursionError`, segfaults, and unexpected types
surface. `FuzzedDataProvider` is the idiomatic way to derive typed inputs.

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
