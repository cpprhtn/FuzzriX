# Crash triage & report

A pile of `crash-*` files isn't a result. Turn each into a **confirmed, deduped, classified finding** with a
reproducer, a root-cause line, a severity, and a fix.

## Per-crash pipeline

1. **Reproduce.** Re-run the binary on the saved input inside the container:
   ```bash
   docker run --rm -v "$PWD/out:/out" fuzzrix-<target> /fuzzer /out/crashes/crash-abc123
   ```
   If it doesn't reproduce → bucket as "needs validation," don't report it as confirmed. **Prove it or park it.**
2. **Minimize.** Shrink the input so the root cause is obvious. libFuzzer's own `-minimize_crash` is the path
   — don't just crank `-runs` on a normal fuzz job (`-minimize_crash=1` itself must be bounded
   with `-runs=N` **or** `-max_total_time=N`; libFuzzer falls back to `-max_total_time=600` if you pass
   neither). The catch: `-max_total_time` caps *each individual run*, not the whole job, and
   libFuzzer does 2 runs per iteration, so budget it as `(timeout - 10) // 2`. Write to a fixed file with
   `-exact_artifact_path` (not `-artifact_prefix`):
   ```bash
   # timeout=120  →  -max_total_time=55
   /fuzzer -minimize_crash=1 \
     -exact_artifact_path=/out/crashes/min-crash-abc123 \
     -max_total_time=55 -timeout=25 \
     /out/crashes/crash-abc123
   ```
   Run 3–5 rounds if time allows (feed each round's output back in). Then optionally **cleanse** —
   overwrite non-essential bytes with garbage so the reproducer carries no incidental data:
   ```bash
   /fuzzer -cleanse_crash=1 \
     -exact_artifact_path=/out/crashes/cleansed-crash-abc123 \
     -timeout=25 -artifact_prefix=/tmp/ \
     /out/crashes/min-crash-abc123
   ```
   **Always re-verify** the minimized/cleansed file still reproduces the *same* `(crash_type, crash_state)`
   (step 5) before accepting it — a smaller input that crashes *differently* is a different bug. (AFL++:
   `afl-tmin -i crash -o min -- /fuzzer @@`.) A 12-byte reproducer beats a 4KB one.

   > `-minimize_crash` guards against drift internally: each round it captures the ASan dedup token from
   > the crash output and stops once the token changes ("looks like a different bug"). For that guard to
   > be live, pass `ASAN_OPTIONS=dedup_token_length=3` into the container for both the minimize and
   > cleanse runs (3 matches the 3-frame `crash_state` key in step 5) — with no token length set the
   > token is empty and the check is a no-op (libFuzzer documents this flag).
3. **Get the stack.** The sanitizer block names the bug type and the faulting line. Capture the top frames —
   that's your root cause anchor.
4. **Classify** in two passes: first *is it a security bug at all*, then *how severe*. Don't eyeball it —
   apply the rules. First normalize the sanitizer's summary line into a **crash_type** token (the same token
   feeds the dedup key in step 5): `heap-use-after-free` → `Heap-use-after-free`, `SEGV on unknown address` →
   `UNKNOWN` (+ a fault address), UBSan `... runtime error: index N out of bounds` → `Index-out-of-bounds`,
   `ERROR: libFuzzer: out-of-memory` → `Out-of-memory`, timeout → `Timeout`.

   **(a) Security-relevant or benign?** Walk this in order; first match wins:

   | Check | Verdict |
   |---|---|
   | output contains an explicit `FuzzerSecurityIssue(Critical\|High\|Medium\|Low)` marker | use that explicit marker |
   | crash_type ∈ **non-security**: `Stack-overflow`, `Out-of-memory`, `Timeout`, `Floating-point-exception`, `Illegal-instruction`, `Unexpected-exit`, or a `Data race` / `Lock-order-inversion` (the last two matched by substring) | **benign** (DoS / resource — report, don't call it a vuln) |
   | UBSan crash_type ∈ `Divide-by-zero`, `Integer-overflow`, `Float-cast-overflow`, `Implicit-conversion`, `Invalid-bool-value` | **benign** |
   | UBSan crash_type ∈ `Bad-cast`, `Index-out-of-bounds`, `Incorrect-function-pointer-type`, `Object-size`, `Non-positive-vla-bound-value` | **security** |
   | generic memory fault (`READ`/`WRITE`/`UNKNOWN`/`Null-dereference`) with fault addr **< 0x1000** | **benign** null deref (DoS) |
   | same, fault addr **≥ 0x1000** | **security** (wild pointer / OOB) |
   | everything else (heap/stack/global overflow, UAF, double-free, use-after-poison) | **security** |

   **(b) Severity** (for security bugs; benign caps at Medium-DoS). Take `crash_category` = first word of
   crash_type, map, then apply the two modifiers:

   | crash_category | Base |
   |---|---|
   | `Bad-cast`, `Heap-double-free`, `Heap-use-after-free`, `Use-after-poison`, `Security DCHECK failure` | **High** |
   | `Container-overflow`, `Heap-buffer-overflow`, `Incorrect-function-pointer-type`, `Index-out-of-bounds`, `Memcpy-param-overlap`, `Non-positive-vla-bound-value`, `Object-size`, `Stack-buffer-overflow`, `UNKNOWN`, `Use-of-uninitialized-value` | **Medium** |
   | not in either list | no severity (don't guess) |

   - **`WRITE` in crash_type → bump one level, capped at High** (an OOB *write* outranks the equivalent read).
     So `Heap-buffer-overflow WRITE` → High; the READ stays Medium.
   - interactive/gesture-gated target → drop one level (rarely applies to a libFuzzer harness).

   Then adjust by **reachability + data-from-outside**: a High bug in an exported parser that eats network
   bytes is worse than the same bug behind three layers of trusted callers. (The severity scale tops out at
   Critical, but the generic ASan analyzer never assigns it on its own — no base crash type maps to Critical
   and the only auto-bump, WRITE, is explicitly capped at High. Critical is reachable only via a manual
   `FuzzerSecurityIssueCritical` marker or product-specific process logic. So for a generic libFuzzer harness
   treat High as the ceiling, and promote to Critical in the report only with a concrete
   exploit-primitive argument.)
5. **Dedup.** Many crash files are the *same* bug. The bucket key is **`(crash_type, crash_state)`** — a
   deterministic signature, not an eyeball judgement. Build `crash_state` once per crash:

   1. Walk the stack top-down. **Drop noise frames**: sanitizer/runtime internals (`__asan_*`, `__interceptor_*`,
      `__sanitizer::*`, `operator new`/`malloc`/`free`/`memcpy` interceptors), libc/loader frames, and any
      line < 3 chars.
   2. From each surviving frame keep the **function name only**: strip `(args)`, `[...]`, anonymous-namespace
      noise, and split on `!`; ignore the `file:line` for the key (it shifts with every recompile).
   3. Take the **first 3** surviving frames (`MAX_CRASH_STATE_FRAMES = 3`).
   4. **Mask volatiles** so two runs of the same bug match: `0x[0-9a-f]{4,}` → `ADDRESS`, drop trailing
      `+0x…` offsets, and large/standalone numbers → `NUMBER` (but leave `file:line` and small constants alone).
   5. Truncate each frame to **80 chars** (`LINE_LENGTH_CAP`), join with newlines.
   6. **Fallback:** if no frames survive (stripped binary, early crash) use the fuzz-target name, else `NULL` —
      every crash still gets a non-empty state.

   Two crashes are the **same bucket** if the `(crash_type, crash_state)` pairs are equal. (A fuzzy matcher —
   two states similar if their longest common subsequence of frame lines is ≥ 2 *or* the average per-line
   similarity ratio exceeds 0.8 — is overkill here; for a one-shot local run exact equality is enough.) Report
   **one finding per bucket** with a representative (minimized) reproducer; note the occurrence count. Skip
   lines containing `:INFO:CONSOLE`, `SUMMARY:`, `WARNING: AddressSanitizer`, or `failed to mprotect` when
   scanning — they are not frames.
6. **Root cause + fix.** Read the faulting line. State *why* the input triggers it (missing bounds check,
   length trusted from input, off-by-one, unchecked return) and give the concrete fix (bounds check, size
   validation, integer-overflow guard, lifetime fix). Then **enforce-forward**: keep this harness in CI so a
   regression re-triggers it.

## Report shape

Lead with a summary, then findings ordered by severity. Prose in the user's language; keep the machine bits
(file:line, sanitizer type) verbatim.

```
# FuzzriX report — <repo> @ <commit>
Run: <engine>, <duration>, <exec/s>, peak cov <edges>.  Targets: <fuzzed>/<total> (ledger below).

## Findings (by severity)

### [High] Heap buffer overflow (WRITE) in parse_header
- Target: parse_header  (src/png.c:88)
- Crash: WRITE of size 4 at src/png.c:94  (ASan: heap-buffer-overflow)  ·  security: yes  ·  severity: High (Medium base + WRITE bump)
- Signature: `(Heap-buffer-overflow WRITE, parse_header / read_chunk / main)`
- Reproducer: out/crashes/min-crash-abc123  (12 bytes)  ·  occurrences: 37 (same signature)
- Root cause: `len` read from input at :90 is used in memcpy at :94 without bounding to the buffer size.
- Fix: validate `len <= buf_cap` before the memcpy; reject otherwise.
- Reproduce: docker run --rm -v "$PWD/out:/out" fuzzrix-parse_header /fuzzer /out/crashes/min-crash-abc123

## Target ledger (cover it or flag it)
| function | file:line | verdict |
|---|---|---|
| parse_header | src/png.c:88 | fuzzed — 1 high |
| decode_frame | src/codec.c:210 | build-failed (missing libfoo-dev) |
| load_config  | src/cfg.c:12  | skipped (trusted input only) |

## Reusable artifacts
- Harness: fuzz/parse_header_harness.cc   ·   Dockerfile: fuzz/Dockerfile.parse_header
- Re-run: bash scripts/run_fuzz.sh fuzz/ out/ 300
```

## Leave it reusable

Commit the harness, Dockerfile, and the minimized reproducers (as regression seeds) into a `fuzz/` dir, and
give the one-line re-run command. The point is that fuzzing becomes permanent, not a one-off.
