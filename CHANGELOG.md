# Changelog

All notable changes to FuzzriX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning.

## [0.5.0] — 2026-06-25

Heavy domains: the playbook learns the harness *shapes* and build moves that
crypto/TLS and media/codec targets need, validated end-to-end on real OSS.

### Added
- **harness-generation** — a "Harness shapes" section beyond feed-bytes-to-one-parser:
  **round-trip** (encode↔decode identity oracle), **differential** (two impls, one
  input), **stateful / structure-aware** (multi-step protocol drivers, grammar
  mutators), and **self-check gates** (CRC/MAC/signature — stub, recompute, or
  disclose). Plus: prefer a project's own maintained fuzzers (`fuzz/`,
  `tools/*_fuzzer.c`, `programs/fuzz/`) over hand-authoring.
- **dockerfile-generation** — narrow huge builds to the surface under test (ffmpeg
  `--disable-everything --enable-decoder=X`, OpenSSL `enable-fuzz-libfuzzer`, mbedTLS
  `programs/fuzz`) so a self-heal round is minutes, not the better part of an hour.
- **corpus-management** — heavy domains live or die on a real seed; source actual
  certs / tiny media files (and the OSS-Fuzz `*_seed_corpus.zip`) — a cold start is
  near-hopeless for structured formats.

### Changed
- **strategy-selection** — flags alone won't move crypto/media; they need one of the
  new harness shapes **plus** a real corpus. Points to the shapes section.

### Fixed
- **dockerfile-generation / self-healing** — two real self-heal gaps from the ffmpeg
  validation: ① autotools `./configure` fails its C-compiler test ("unable to create
  an executable") when sanitizer flags are only in `--extra-cflags` — they must also
  be in `--extra-ldflags`; ② codec libs need `--disable-asm` (hand-written SIMD isn't
  coverage-instrumented and breaks the link on arm64 with `undefined reference to ff_*_neon`).

### Validated
- **mbedTLS X.509 DER parse** (crypto/TLS) — built first try, 4.7M execs / 91s
  (~52k exec/s), cov 1203; no crash (hardened).
- **ffmpeg MJPEG decode** (media/codec) — built after the two self-heals above, 181k
  execs / 91s, cov 6348 / ft 25268; no crash (hardened). Both are *fuzzed, no finding*
  ledger results, not "all clear."

## [0.4.1] — 2026-06-24

A correctness patch for the validation methodology: a single timed fuzz run is
noise, and one of our conclusions was drawn from that noise.

### Fixed
- **strategy-selection** — the dictionary verdict was wrong. A single-trial ablation
  made a dict look *coverage-neutral or slightly negative* on cJSON; a 3-trial median
  shows it is a small but consistent **positive** (+~5% features), and a large win
  behind a string/magic gate. Re-scoped from "skip on punctuation grammars" to
  "always worth applying; biggest behind a string/magic gate."

### Changed
- **strategy-selection** Discipline now mandates comparing strategies over **≥3
  trials on the median**, never one run — a fixed `-seed` does not remove the
  several-percent run-to-run swing that can flip a verdict.
- **ablation/bench** — `--trials N` reports the median coverage/features (crash =
  found in any trial); single-trial output is documented as a smoke check, not a
  measurement.

### Notes
- `docs/EVALUATION.md` "Honest limits" now records the stochasticity, short-time-cap,
  and `corpus_size`-is-a-proxy caveats explicitly.

## [0.4.0] — 2026-06-24

Validation bench widened to a 5-language × multi-domain matrix; the gaps it
surfaced were fixed in the playbook.

### Added
- Image domain validated end-to-end (`stb_image`) — the bench now spans parser ·
  calc · compression · xml · url · image across **C · C++ · Rust · Go · Python**
  (all build + fuzz; Go via `go test -fuzz`).

### Changed
- **dockerfile-generation** — dictionary values must escape non-printable bytes as
  `\xNN`; a raw `\r`/`\n` makes libFuzzer reject the *entire* dict
  (`ParseDictionaryFile error`), silently dropping it. (Image/binary magics bite.)
- **fuzzing-run** — coverage is reported differently per engine (native libFuzzer
  `cov:`/`ft:` vs atheris `corp:` vs Go `new interesting`); fall back to the
  corpus/interesting count when `cov:` is absent instead of reporting a dead run.
- **harness-generation** — atheris instruments *Python bytecode* only; a native C
  extension (e.g. `ujson`) is a black box unless the extension is built with
  coverage — disclose whether the native layer was actually instrumented.

### Notes
- Heavy domains (TLS/crypto, media/ffmpeg) are deferred to a later release rather
  than faked with light stand-ins.

## [0.3.0] — 2026-06-24

Skill tuned from research + a 5-language validation bench (no new structure — the
playbook's *judgment* got sharper, backed by data).

### Changed
- **strategy-selection** — value_profile emphasized as the most consistent coverage
  win (ablation); dictionary re-scoped to "when there's a string/magic gate"
  (coverage-neutral on punctuation grammars like JSON).
- **crash-triage** — the LLM analyst owns root cause (beats mechanical heuristics on
  unsymbolized panics / deep call stacks); added an explicit "memory-safe runtime
  (Python exception, Rust panic) = benign" classification rule.
- **context-extraction** — reading source is *aiming, not detection*: predict the
  suspicious operation, then aim harness/seed/dict at it; the engine confirms.
- **coverage-iteration** — the coverage-loop payoff scales with target depth;
  diagnose with `-print_coverage` before spending rounds.
- **dockerfile-generation** — self-heal CMake-generated headers (e.g. `*_export.h`)
  with a minimal export-macro stub.

### Validated
- 5-language OSS matrix (C · C++ · Rust · Go · Python) all build + fuzz; Go stack
  exercised end-to-end (`go test -fuzz`).

## [0.2.0] — 2026-06-24

### Added
- **Strategy selection** (`references/strategy-selection.md`) — a deterministic, justified choice of
  libFuzzer knobs (value_profile, dictionary, fork, max_len) per target, with rationale.
- **Corpus management** (`references/corpus-management.md`) — seeding, `-merge=1` minimization, and
  persist-and-reuse across runs, all in one container.
- **Coverage-improvement loop** (`references/coverage-iteration.md`) — a bounded feedback loop to widen the
  harness's reach (the biggest performance lever).
- **`CLAUDE.md`** — agent guide for working in this repo.
- **"Four hats" framing** and an **8-step loop** (added the strategy and coverage-improvement phases).
- **Korean documentation** (`README.ko.md`) plus a "respond in the user's language" guideline.
- `-use_value_profile=1` on by default in `run_fuzz.sh` (helps get past magic/length gates).

### Changed
- **Crash triage** — `(crash_type, crash_state)` deduplication, security/benign classification, and a
  severity mapping (with an OOB-write bump).
- Expanded `harness-generation`, `dockerfile-generation`, and `fuzzing-run` with exact libFuzzer flags,
  exit-code handling, and per-stack build details.
- **README restructured** — install and requirements moved up; roadmap removed (history lives here).

### Removed
- Legacy taglines ("Fuzz + Matrix + X" and the "successor to Longinus" framing).

## [0.1.1] — 2026-06-23

### Added
- **Docker as a hard prerequisite** — if it's unavailable, stop with an install pointer instead of running
  on the host.
- **First-reply framing reset** — when called with "find the bugs," state up front that the skill builds a
  fuzzer and lets the engine find them.

## [0.1.0] — 2026-06-23

### Added
- Initial release as an agent skill (Claude Code + Codex).
- C/C++ libFuzzer MVP; multi-stack support: **Python/Atheris**, **Rust/cargo-fuzz** (Go routed).
- Self-healing build loop, BYOD Docker isolation, resource caps.
- Harness + Dockerfile templates (`cpp-libfuzzer`, `python-atheris`).
- Helper scripts: `scan_targets.py` (fuzzing-surface identification), `run_fuzz.sh` (capped Docker run).
- Reference playbook: authorization, context extraction, harness/Dockerfile generation, self-healing,
  fuzzing run, crash triage.
