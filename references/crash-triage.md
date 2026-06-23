# Crash triage & report

A pile of `crash-*` files isn't a result. Turn each into a **confirmed, deduped, classified finding** with a
reproducer, a root-cause line, a severity, and a fix.

## Per-crash pipeline

1. **Reproduce.** Re-run the binary on the saved input inside the container:
   ```bash
   docker run --rm -v "$PWD/out:/out" fuzzrix-<target> /fuzzer /out/crashes/crash-abc123
   ```
   If it doesn't reproduce → bucket as "needs validation," don't report it as confirmed. **Prove it or park it.**
2. **Minimize.** Shrink the input so the root cause is obvious:
   ```bash
   /fuzzer -minimize_crash=1 -runs=10000 -artifact_prefix=/out/crashes/min- /out/crashes/crash-abc123
   ```
   (AFL++: `afl-tmin`.) A 12-byte reproducer beats a 4KB one.
3. **Get the stack.** The sanitizer block names the bug type and the faulting line. Capture the top frames —
   that's your root cause anchor.
4. **Classify** by the sanitizer/symptom:

   | Sanitizer / symptom | Bug class | Typical severity |
   |---|---|---|
   | `heap-buffer-overflow` (WRITE) | OOB write | **Critical** — often exploitable (RCE) |
   | `heap-buffer-overflow` (READ) | OOB read | High — info leak / crash |
   | `heap-use-after-free`, `double-free` | UAF / lifetime | **Critical** |
   | `stack-buffer-overflow` | stack OOB | **Critical** |
   | `global-buffer-overflow` | global OOB | High |
   | UBSan: signed overflow / shift / misaligned | undefined behavior | Medium (context-dependent) |
   | `SEGV on unknown address` (null/low) | null deref | Medium — DoS |
   | `out-of-memory` / `allocation-size-too-big` | unbounded alloc from input | Medium — DoS |
   | `timeout` / hang | algorithmic blowup / inf-loop | Medium — DoS |
   | assertion failure / `abort` | invariant violation | Low–Medium |

   Adjust by **reachability + data-from-outside**: a critical bug in an exported parser that eats network
   bytes is worse than the same bug behind three layers of trusted callers.
5. **Dedup.** Many crash files are the *same* bug. Bucket by `(bug class + top 2–3 stack frames)`. Use
   `scripts/crash_dedup.py out/crashes` if present, or group by the ASan summary line. Report one finding per
   bucket with a representative (minimized) reproducer; note the count.
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

### [Critical] Heap buffer overflow in parse_header
- Target: parse_header  (src/png.c:88)
- Crash: WRITE of size 4 at src/png.c:94  (ASan: heap-buffer-overflow)
- Reproducer: out/crashes/min-crash-abc123  (12 bytes)  ·  occurrences: 37 (deduped)
- Root cause: `len` read from input at :90 is used in memcpy at :94 without bounding to the buffer size.
- Fix: validate `len <= buf_cap` before the memcpy; reject otherwise.
- Reproduce: docker run --rm -v "$PWD/out:/out" fuzzrix-parse_header /fuzzer /out/crashes/min-crash-abc123

## Target ledger (cover it or flag it)
| function | file:line | verdict |
|---|---|---|
| parse_header | src/png.c:88 | fuzzed — 1 critical |
| decode_frame | src/codec.c:210 | build-failed (missing libfoo-dev) |
| load_config  | src/cfg.c:12  | skipped (trusted input only) |

## Reusable artifacts
- Harness: fuzz/parse_header_harness.cc   ·   Dockerfile: fuzz/Dockerfile.parse_header
- Re-run: bash scripts/run_fuzz.sh fuzz/ out/ 300
```

## Leave it reusable

Commit the harness, Dockerfile, and the minimized reproducers (as regression seeds) into a `fuzz/` dir, and
give the one-line re-run command. The point is that fuzzing becomes permanent, not a one-off.
