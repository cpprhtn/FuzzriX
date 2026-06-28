# Changelog

All notable changes to FuzzriX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning.

## [0.11.0] — 2026-06-28

New deterministic helper — **seed-corpus bootstrap** — completes the loop toolkit
(target selection · gate-passing dict · **seeds** · coverage diagnosis · run).

### Added
- **`scripts/collect_seeds.py`** — builds a seed corpus from the target repo, with
  the `corpus-management.md` discipline baked in: pull data files from the sample
  dirs (`test*/`, `samples/`, `testdata/`, `fixtures/`, `corpus/`, …) while skipping
  source/build/doc files, **unpack `*_seed_corpus.zip`** (the OSS-Fuzz convention),
  cap at 5 MB, dedup by content, and write each seed under its sha256 name (flat,
  merge-friendly). `--ext png,jpg` matches a known format anywhere instead. A good
  seed is the cheapest way past a format gate (the Magma libpng run showed it).
  Wired into `corpus-management.md`, `00-map.md`, `SKILL.md`, `CLAUDE.md`, `AGENTS.md`.

## [0.10.2] — 2026-06-25

Three more verification rounds (7–9) on the parts the first pass didn't reach —
crash dedup, single-file scanning, the eval CSV.

### Fixed
- **crash dedup was splitting one bug** — the `crash_state` signature dropped
  sanitizer/libc frames but **not the harness entry point**, so the *same* bug
  bucketed differently depending on whether `LLVMFuzzerTestOneInput` happened to
  parse into the top-3 (and on its address/line, which shift every recompile). The
  harness driver (`LLVMFuzzerTestOneInput` / Jazzer `fuzzerTestOneInput` / atheris
  `TestOneInput`) is now excluded from the dedup state, so the same bug merges and
  distinct bugs stay separate. (`crash-triage.md` step 5 updated to match.)
- **`scripts/scan_targets.py` silently returned `count: 0` for a single-file
  argument** (`rglob('*')` yields nothing on a file) — it now scans a lone file
  like the other helpers.
- **(core, local) the multi-trial bench wasn't independent** — every trial reused
  one `/tmp/fuzzrix-bench-<name>` dir, so trial N started from trial N-1's *grown*
  corpus (biasing the median, which assumes independent samples) and later trials
  clobbered earlier crash artifacts. Each trial now runs in its own wiped dir
  (validated: two cJSON trials kept separate ~1.4k-file corpora, not a cumulative
  one). `ablation` already used unique per-run dirs — unaffected.

### Verified
- crash dedup merges same-bug/different-address and keeps distinct bugs apart, and
  is stable against recompile-volatile frame suffixes (lambda/clone numbers);
  `eval.write_metrics` emits a clean metrics CSV.
- **the third template now built end-to-end** (`python-atheris` — atheris compiled,
  caught an `IndexError`), so all three starters are confirmed building as shipped;
  the harness-frame dedup fix was validated on that real atheris crash (`bucket =
  IndexError || parse`, `TestOneInput` excluded). `surface.identify` (wraps the
  scanner) inherits the macro-API fix; `pipeline.run` guards empty candidates;
  `scan_targets` is graceful (count 0, no crash) on Rust/Go/Python; `llm` degrades
  to a heuristic backend with no API key. Two more rounds (10–11) surfaced no new
  bugs. Full suite green (97 tests).

## [0.10.1] — 2026-06-25

A 6-round verification & hardening pass over everything shipped so far — running
the helpers on edge cases, building all three templates, scanning real targets,
checking flag defaults against the live engine, and re-reading the docs.

### Fixed
- **crash classification gaps** (found by building the cpp template and feeding real
  sanitizer output through the analyst):
  - a **UBSan `runtime error:` now wins over a co-occurring `libFuzzer: deadly signal`**
    — previously a UBSan-caught out-of-bounds that aborted was mislabeled a benign
    "abort" instead of a security memory bug;
  - **LeakSanitizer** is parsed as `memory-leak` (was the garbage type `detected`);
  - **SEGV** is split by fault address — near-null ⇒ benign null-deref, non-null ⇒
    security (wild pointer); **abort / assertion** failures are named and classified;
  - UBSan memory-unsafety (`index … out of bounds`, object-size, bad-cast) classifies
    as security (the spaced spelling was slipping through).
  - **double-free** was parsed as the filler word `attempting` (so the CWE-415
    mapping never fired) — the parser now takes the normalized type from the
    `SUMMARY` line.
  These keep the local analyst core consistent with `crash-triage.md`.
- **`scripts/scan_targets.py` — it missed the real entry points.** Export-macro-wrapped
  public functions (`CJSON_PUBLIC(cJSON *) cJSON_ParseWithLength(...)`) weren't detected
  at all (cJSON/libpng/sqlite/openssl all wrap their API this way); now they are, and
  rank #1. Also: internal allocators (`internal_realloc`) are deprioritized, public
  (non-`static`) functions get a surface boost, and the name regex now matches a
  CamelCase/`_`-joined `Parse` (not just a leading word). On cJSON, `cJSON_ParseWithLength`
  went from *undetected* to the top result.
- **`scripts/run_fuzz.sh` — the OOM-headroom invariant was violated.** It set
  `--memory=2g` *and* `-rss_limit_mb=2048` (equal — zero headroom), so a memory-heavy
  target got Docker-OOM-killed with **no artifact** instead of a clean libFuzzer `oom-*`.
  `-rss_limit_mb` is now derived ~1 GB below `--memory` (default bumped to `3g` ⇒ rss
  `2048`, preserving fuzzing room).
- **`scripts/cover_gaps.py`** — a missing log file now prints a clean error (exit 2)
  instead of a traceback, matching the other helpers.

### Changed
- **crash-triage** — added the `Memory-leak` and `assertion / abort` benign rows.
- **fuzzing-run** — the `-rss_limit_mb` row now states it's derived ~1 GB below
  `--memory` (was a stale `2560` that didn't match the runner).
- **SKILL.md** — the coverage step now names `cover_gaps.py` (entry-point sync).

### Verified
- All three starter templates build end-to-end as shipped: `cpp-libfuzzer` (caught
  the injected OOB), `jvm-jazzer` (caught snakeyaml's RCE), `python-atheris`
  (structure + the baked-in atheris-install fixes).
- Every libFuzzer flag default the docs cite (`entropic=1`, `use_value_profile=0`,
  `rss_limit_mb=2048`, `timeout=1200`, …) checked against `‑help=1` on the live engine.
- All `fuzzrix/*` modules import; `report.to_markdown` / `regress.generate` produce
  sound output. Full suite green (93 tests).

## [0.10.0] — 2026-06-25

New deterministic helper — **coverage-gap diagnosis** — gives the coverage loop
(the top performance lever) a tool, not just prose.

### Added
- **`scripts/cover_gaps.py`** — parses libFuzzer `-print_coverage=1` into a ranked
  plan: **frontier** (functions entered but partly covered, ranked by uncovered
  edges — push these first with a seed/dict nudge) vs **unreached** (never entered,
  ranked by size — a gated region needing a new seed/dict, or a harness-shape gap).
  `--src` drops libc/system noise; handles C++ demangled names. Wired into
  `coverage-iteration.md`, `00-map.md`, `CLAUDE.md`, and `AGENTS.md`.

### Validated
- On the cJSON image it cleanly surfaced the frontier (`parse_value` 309/696,
  `parse_string` 71/220 — where to push) and the unreached API (`cJSON_Compare`,
  `cJSON_Duplicate` — never called by a parse-only harness). +4 tests (81 total).

## [0.9.0] — 2026-06-25

Magma multi-target ground-truth integration (the external-validity benchmark).

### Added
- (core, local) **`fuzzrix.magma`** — consumes Magma's ground truth: parses the
  monitor CSV (`PNG001_R/_T` reached/triggered counters), builds the bug→file
  catalog straight from `targets/<t>/patches/bugs/*.patch` (no hardcoded table),
  and scores whether the engine triggered a known bug + whether the analyst's
  crash frame lands in that bug's file. Tested end-to-end on the real libpng
  catalog (7 PNG bugs); +6 tests (76 total).

### Changed
- **dockerfile-generation** — generalized the "disable hand-written SIMD" note:
  libpng needs `--enable-arm-neon=no` (else `arm/filter_neon.lo` won't compile on
  arm64), alongside ffmpeg's `--disable-asm` — same root cause, per-project flag.

### Validated / honest limits
- Built Magma's libpng with all 7 bug patches **live** (3 self-heals: the
  `MAGMA_AND` canary macro, `--enable-arm-neon=no`, `-include cstdlib`). The engine
  ran 2.78 M execs / 151 s and a PNG chunk-type dict measurably deepened reach into
  the chunk handlers — but **no bug triggered in ≤151 s**, as expected: Magma bugs
  are deep and its campaigns run *hours*. The scorer is ready; a long campaign is
  the open step (see `docs/EVALUATION.md`).

## [0.8.1] — 2026-06-25

Documentation audit: fix drift, tighten verbose passages, verify every link.

### Fixed
- **SKILL.md & AGENTS.md drift** — both entry points were missing the **Java/JVM
  (Jazzer)** stack (added in 0.7.0) and the **`mine_dict.py`** helper (0.8.0). Added
  the JVM stack row + `pom.xml`/`build.gradle` detection, the dict-miner to the
  synthesis step and the Codex helper list, and the `python-atheris`/`jvm-jazzer`
  templates to AGENTS.md.

### Changed
- **strategy-selection** — the dictionary cell was a 1,300-char run-on; halved it
  without losing the guidance (mine with `mine_dict.py`, the stb_image result, the
  single-trial-noise caveat now points to Discipline instead of re-explaining it).
- **harness-generation** — dropped a managed-runtime "catch only expected exceptions"
  restatement in the Python section that the engine-model rule already covers.
- Verified all reference/SKILL/AGENTS cross-links and anchors resolve.

## [0.8.0] — 2026-06-25

New deterministic helper — **dictionary mining** — closes the gap between
"synthesize a dict" advice and a tool that does it, validated to find a bug.

### Added
- **`scripts/mine_dict.py`** — builds a libFuzzer/AFL++ dictionary from the target's
  own source: string literals + magic byte-arrays (hex `{0x89,…}`, char `{'P','N','G'}`,
  and **decimal** `{137,80,…}` gated on a signature context to keep lookup tables out),
  scored by gate-proximity (`memcmp`/`strncmp`/…) and escaped for libFuzzer (control
  bytes → `\xNN`, so the file is never rejected). Wired into `strategy-selection.md`,
  `00-map.md` (helper table), and `CLAUDE.md`.

### Validated
- 3-trial ablation on `stb_image`: a **mined dict found a decoder crash within a 20 s
  cap that the no-dict and value-profile-only runs did not** (its lower `cov`/`ft` is
  the stop-at-first-crash artifact, not a regression). The mined PNG/JFIF/RADIANCE
  magics drove the fuzzer to a real bug fast.

## [0.7.0] — 2026-06-25

New language stack — **Java/JVM via Jazzer** — added end-to-end and validated by
catching a real CVE; plus the external-validity matrix grows to two real bugs.

### Added
- **Java / JVM stack (Jazzer)** — `references/harness-generation.md` gains a Java/JVM
  section (FuzzedDataProvider harness, `jazzer_driver` wiring that reuses the
  `/fuzzer` path, and the bug-detector finding model: RCE/SSRF/injection/unsafe
  deserialization), a `templates/jvm-jazzer/` starter, and routing in `00-map.md`
  (`pom.xml`/`build.gradle`) + `fuzzing-run.md`. The engine-model table marks JVM ✅.
- (core, local) `analysis.parse` now understands Jazzer's `== Java Exception:` output
  (security-issue vs plain exception, target-framed stack skipping `jaz.Zer`/jdk),
  and `classify` grades a `FuzzerSecurityIssue` as a real security finding vs a
  managed-runtime DoS for a plain exception.

### Fixed
- **harness-generation** — two real self-heal hits building the JVM target:
  `javac` needs `-encoding UTF-8` (the base image defaults to US-ASCII, so any
  non-ASCII source byte fails), and arm64 hosts must pull the x64 base image with
  `DOCKER_DEFAULT_PLATFORM=linux/amd64`.

### Validated
- **snakeyaml 1.30 / CVE-2022-1471** (Java/Jazzer) — the engine triggered the
  unsafe-deserialization **RCE** (default `Yaml().load`) via Jazzer's bug detector;
  crash proven by re-run, analyst scored crash-type + site + provenance and
  classified it security/High. Second real CVE in the external matrix (after
  libxml2), and the first on a non-C stack.

## [0.6.0] — 2026-06-25

External ground truth: validate the skill against a **real historical CVE**, not
just self-injected dogfood bugs — and score both pillars (did the engine trigger
*the* bug, did the analyst name the right function + CWE).

### Added
- **Ground-truth eval** — the oracle now carries `provenance` (`injected` vs
  `external-real`) and an expected `crash_type`; the scorer adds a `crash_type`
  match and breaks the summary out **by provenance**, so external validity is
  reported separately from pipeline-wiring validity.
- **crash-triage** — a "known upstream bug vs. novel finding" discipline: a crash in
  a third-party library pinned to an old version may be already-fixed upstream;
  report it as *reproduces-a-known-bug / upgrade-to-fix*, not as a 0-day.

### Validated
- **libxml2 2.9.2** (external CVE) — built first try (the v0.5.0 autotools
  `--extra-ldflags` fix held on a second target), the engine re-found a real
  heap-buffer-overflow (OOB read) in `xmlParseXMLDecl` from a UTF-16-BOM input, and
  the analyst scored **4/4**: crash type, crash site (file/function/line), root-cause
  function, and CWE-125 all correct. Crash proven by re-run.

## [0.5.1] — 2026-06-25

A measurement patch: make per-engine coverage honest — parse Go's proxy, and
always label whether a number is real edge coverage or a corpus-size proxy.

### Fixed
- **fuzzing-run** — Go's native fuzzer emits no edge count; its corpus size lives in
  `new interesting: K (total: M)`, which the parser now reads (previously Go reported
  no coverage at all). The atheris/Go fallback is now explicitly tagged as a *proxy*,
  not edge coverage, and called out as non-comparable across engines.

### Changed
- **fuzzing-run** — the per-engine coverage note now spells out the three sources
  (`edges` from libFuzzer `cov:`, `libfuzzer-corpus`, `go-corpus`) and that a corpus
  count tracks progress only *directionally within one engine*.

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
