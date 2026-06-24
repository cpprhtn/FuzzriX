# Context extraction — profile & find target functions

Goal of this phase: know the **stack + build system**, and produce a **ranked list of target functions** —
the places where external/attacker-controlled data enters and could corrupt memory or state.

## 1. Profile the project

Detect by build/manifest files (cheap greps, do them in one batch):

| Files present | Stack | Build system | Default engine |
|---|---|---|---|
| `*.c`, `*.h` | C | Make / CMake / autotools | libFuzzer |
| `*.cc`, `*.cpp`, `*.hpp` | C++ | CMake / Make / Meson | libFuzzer (AFL++ if no clang) |
| `pyproject.toml`, `setup.py`, `*.py` | Python | pip / poetry | Atheris |
| `Cargo.toml` | Rust | Cargo | cargo-fuzz |
| `go.mod` | Go | go | native `go test -fuzz` |

Also note: external deps (these often *are* the parsing surface — image/codec/compression/crypto libs),
whether clang/sanitizers are reachable, and any existing `fuzz/`, `test/`, `corpus/`, or sample-input dirs
(free seed corpus).

## 2. What makes a good target function

Prioritize functions where **outside data meets memory-unsafe operations**. Signals, strongest first:

1. **Takes a raw buffer + length**: `(const uint8_t* data, size_t size)`, `(char* buf, int len)`,
   `(void* p, size_t n)` — already fuzz-shaped.
2. **Parses / decodes / deserializes**: names like `parse_*`, `decode_*`, `read_*`, `load_*`, `unpack_*`,
   `deserialize_*`, `from_bytes`, `*_handler`; file-format or protocol parsers.
3. **Ingests external input**: reads a file/path, a socket/packet, stdin, an env var, or a network field.
4. **Touches unsafe primitives**: `memcpy`/`memmove`/`strcpy`/`strcat`/`sprintf`/`alloca`, manual
   index/pointer arithmetic, `malloc` sized from input, casts of input into structs.
5. **Reachable**: exported / public API, or called from an entry point — not dead code.

De-prioritize: pure getters, code with no external input, anything requiring elaborate global state to call.

## 2b. Think like the attacker, not the author (the analyst hat)

This is the **target-analyst / threat-modeler** hat. Read the code *and* the author's intent — but rank and
harness from an **attacker's threat model**, because that's what most users actually want (CVEs, not a feature
audit), and because **bugs live exactly where the author's intent and the code's real behavior diverge.**

- **Intent is your baseline, not your verdict.** Understanding what a parser is *supposed* to accept tells you
  (a) how to get a harness *past* the front-door validation into the meaty logic, and (b) what counts as a real
  bug (a crash / memory error) vs intended behavior (rejecting bad input with an error is **not** a bug). You
  set this baseline; the **engine** finds the divergence from it — you never declare a vuln by reading code.
- **Trace the untrusted-data path.** For each candidate, ask: where does attacker-controlled data enter, what
  transformations does it pass through, and which memory-unsafe operation does it eventually reach? Rank by
  **reachability-from-untrusted-input × depth-of-memory-unsafety**, not by what the product "cares about."
- **Harvest harness fuel while you read.** The same pass should collect: the **input contract / format** of each
  target (so the harness reaches deep code), **seed candidates** (valid sample inputs), and **dictionary
  tokens** (magic bytes, keywords, format markers). These feed [strategy-selection.md](strategy-selection.md),
  [corpus-management.md](corpus-management.md), and the [coverage loop](coverage-iteration.md) — getting past a
  format gate is often a bigger win than more run time.
- **Predict, then aim — your reading is *aiming*, not detection.** When the source suggests a specific
  dangerous operation (a numeric cast like `(unsigned int)(x)` that `NaN`/`Inf` breaks, a `memcpy` sized from
  input, recursive descent with no depth cap), treat it as a **hypothesis** and aim the harness + seed + dict
  straight at it — e.g. predict a `fac`/`ncr` cast bug → seed `fac(0/0)` to drive a `NaN` into it. You do
  **not** declare it a bug; you point the engine at your hypothesis so it confirms or refutes it fast. In
  practice a read-the-code prediction lands the exact bug — but only the engine proves it, prioritizes it, and
  classifies it (security vs benign). Good hypotheses make the engine fast; the engine, not you, is the oracle.

## 3. Run the scanner

```bash
python3 scripts/scan_targets.py <repo>            # ranked JSON candidates
python3 scripts/scan_targets.py <repo> --top 10   # limit
python3 scripts/scan_targets.py <repo> --lang c   # force a language
```

It uses `tree-sitter` if the bindings are installed (accurate signatures), and falls back to regex heuristics
otherwise. Output per candidate: `file`, `line`, `name`, `signature`, `score`, `reasons`. Treat the score as a
*starting* rank — apply your own reachability judgment on top.

**Scope:** the scanner's heuristics are tuned for **C/C++** function signatures. On a Python/Rust/Go repo it
will often return `count: 0` — that's expected, not a clean bill. Fall back to the §2 signals by hand: pick
the public parse/decode entry point that takes the outside bytes (e.g. `def tokenize(data)`,
`pub fn parse(data: &[u8])`, `func FuzzX(f *testing.F)`) and harness it directly.

## 4. Build the target ledger

Track every candidate you'll act on, and **every one you skip**:

| function | file:line | why a target | verdict |
|---|---|---|---|
| `parse_header` | `src/png.c:88` | takes `(uint8_t*,size_t)`, memcpy from input | → fuzzed |
| `decode_frame` | `src/codec.c:210` | decoder, reachable | → build-failed (missing dep, see notes) |
| `load_config` | `src/cfg.c:12` | reads file but trusted-only input | → skipped (not attacker-facing) |

The ledger is the backbone of "cover it or flag it" — an un-harnessed sink must appear here with a reason,
never silently dropped.

## Next

Pick the top target(s) → write the harness ([harness-generation.md](harness-generation.md)) and the
Dockerfile ([dockerfile-generation.md](dockerfile-generation.md)).
