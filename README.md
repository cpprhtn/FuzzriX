# FuzzriX

**English** · [한국어](README.ko.md)

**AI-driven universal fuzzing accelerator — an LLM as fuzzing engineer + crash analyst.**

> Fuzzing is the strongest bug-finding technique we have, but the LLM's role in it has been miscast. Asking a
> model to *read code and point at bugs* is hallucination-prone and low-precision. FuzzriX casts the LLM as a
> **fuzzing engineer + crash analyst** instead: it ① **synthesizes** a fuzzer tailored to the target from
> known fuzzing theory, and ② **analyzes the root cause** of the crashes a deterministic engine finds. The
> LLM builds the fuzzer and explains the crashes — it does **not** do the bug-finding itself.

Point an AI agent at a repo and FuzzriX **stands up a real fuzzer for it, runs it in isolation, and brings
back triaged crashes** — each with a reproducer, a root-cause line, and a fix.

## Install

FuzzriX ships as an agent skill usable by **Claude Code** and **Codex**.

### Claude Code

```bash
git clone https://github.com/cpprhtn/FuzzriX.git
ln -s "$(pwd)/FuzzriX" ~/.claude/skills/fuzzrix
```

Then in Claude Code: *"fuzz this project"* / *"set up libFuzzer for the parser"* / *"퍼징 돌려줘"*.

### Codex / other agents

Point the agent at this repo; it reads [AGENTS.md](AGENTS.md) → [SKILL.md](SKILL.md) and follows the same
playbook.

## Requirements

- Docker (all building/fuzzing happens in containers).
- Python 3 for the helper scripts (`scripts/scan_targets.py`).
- An agent that supports skills (Claude Code) or `AGENTS.md` (Codex).
- *Optional:* `tree-sitter` Python bindings for higher-fidelity surface extraction (the scanner falls back to
  regex heuristics without them).

## Why this framing

The LLM is placed where it's strong and kept out of where it's weak:

| Stage | Who does it | Why |
|---|---|---|
| **Synthesis** (pre) | LLM = engineer | Translating known fuzzing theory (structure-aware, differential, stateful, dictionary) into target-specific harness/strategy code is a generative task LLMs do well. |
| **Detection** | deterministic engine (libFuzzer / AFL++ / …) | Finding bugs is what coverage-guided fuzzers are *built* for — reproducible, no hallucination. **The LLM is out of this loop.** |
| **Analysis** (post) | LLM = analyst | Root-cause reasoning runs on ground truth (sanitizer output + source + reproducer), so it's high-precision — the LLM's best output. |

## How it's different

- **The LLM is a fuzzing engineer + analyst, not a bug detector — no BYOK.** FuzzriX is a **skill**: the agent
  already running (Claude Code, Codex, …) *is* the model. It synthesizes the harness/strategy, reads compiler
  errors and fixes them, and analyzes each crash — but **detection is done by a deterministic engine, with the
  LLM out of that loop.**
- **Zero host pollution (BYOD).** Every toolchain and build runs **inside Docker**. Your host only ever sees
  source files and crash artifacts.
- **Self-healing builds.** Synthesized harnesses rarely compile first try. FuzzriX captures `stderr`, feeds it
  back to the agent, and rebuilds — a bounded loop until it works or honestly reports why it can't.
- **Evaluable by design.** Each run is structured to yield metrics (build success, time-to-first-crash,
  root-cause accuracy, dedup) so claims are backed by numbers, not vibes.

## What you get

```
synthesize fuzzer (strategy + harness + Dockerfile) → build & self-heal
   → run deterministic engine (capped) → analyze crashes (root cause + fix + regression test)
   → report + metrics
```

A reusable, target-tailored fuzzer left in your repo **+** a ranked, triaged crash report — each crash with a
reproducer, a root-cause line, a CWE class, a fix, and a regression test. Plus machine-readable metrics for
evaluation. (Not a list of "bugs spotted by reading code.")

## Safety

FuzzriX fuzzes **code you own or are authorized to test**, **in a sandbox** — never live production services
or remote hosts. It runs target code only inside Docker and caps CPU/RAM/disk/time. See
[references/authorization.md](references/authorization.md).

## Status

**v0.7.0.** The thesis is *"LLM = fuzzing engineer + crash analyst."* Working today: the Docker-isolated
engine, self-healing builds, multi-stack harness synthesis (C/C++ · Python/Atheris · Rust/cargo-fuzz ·
**Java/JVM/Jazzer** · Go), non-trivial harness shapes (round-trip · differential · stateful · checksum-gate),
strategy selection, corpus management, and a coverage-improvement loop — validated on heavy domains (crypto/TLS,
media/codec) and against **real external CVEs** (libxml2 heap-overflow re-found with a 4/4 analyst score;
snakeyaml's CVE-2022-1471 RCE caught on the JVM stack). Version history: [CHANGELOG.md](CHANGELOG.md).

## License

See [LICENSE](LICENSE).
