# Changelog

**English** · [한국어](CHANGELOG.ko.md)

All notable changes to FuzzriX are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic versioning.

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
