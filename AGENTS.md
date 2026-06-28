# FuzzriX — agent operating guide (Codex / generic agents)

> Claude Code loads this skill via **[SKILL.md](SKILL.md)** (frontmatter-routed). Codex CLI and other
> agents that read `AGENTS.md` should follow the same playbook — the content is portable markdown; only the
> entry point differs. **Read [SKILL.md](SKILL.md) and the [references/](references/) it links; this file is
> just the Codex-facing pointer + invariants.**

## What this is

FuzzriX is an AI-driven universal fuzzing accelerator. **The LLM is a fuzzing engineer + crash analyst, NOT a
bug-finding oracle.** You (the agent)
do two things: **(synthesis, pre)** identify the fuzzing surface, pick a strategy, write a harness +
Dockerfile, build them in an isolated container, and **self-heal** compile errors in a bounded loop; then
**(analysis, post)** take the crashes a deterministic coverage-guided engine finds and report their root
cause, classification, fix, and a regression test. **Detection — the actual bug-finding — is the engine's
job (libFuzzer / AFL++ / …), not yours.** You never read source and point at vulnerabilities; that's an
explicit non-goal. **You are the LLM in the loop — there is no external API key to configure.**

## When to engage

The user asks to fuzz a project, write a fuzz harness, find memory bugs/crashes, add libFuzzer / AFL++ /
Atheris / cargo-fuzz, set up continuous fuzzing, or mentions "FuzzriX / 퍼징".

## Hard invariants (do not violate)

1. **Authorization gate first.** Fuzz only code the user owns or is permitted to test. Never point a fuzzer
   at a live production service or remote host — FuzzriX fuzzes code in a sandbox. See
   [references/authorization.md](references/authorization.md).
2. **Zero host pollution (BYOD).** Compile and run target code **only inside Docker**. The host sees source
   files and crash artifacts, nothing else.
3. **Cap resources before launching.** Time, cores, RAM, disk. Default to short runs.
4. **Self-heal, bounded.** Build → on failure capture `stderr` → fix harness/Dockerfile → rebuild. Max 3
   rounds by default; then disclose why and move on. Never fake a successful build.
5. **Prove the crash.** A crash is real only when its saved testcase reproduces it on re-run. Otherwise it's
   "needs validation."
6. **Cover it or flag it.** Every extracted target ends with a verdict: fuzzed / skipped+why / build-failed+why.

## The loop (full detail in SKILL.md)

`profile → identify fuzzing surface (attacker threat model) → synthesize strategy + harness + Dockerfile →
build & self-heal → fuzz (deterministic engine) → improve coverage (bounded run→diagnose→fix→re-run loop) →
analyze crashes (root cause + fix + regression test) & report`

Walked wearing four hats, one agent: **target analyst/threat-modeler** (rank by attacker reachability; intent
is the baseline, the engine finds where behavior diverges from it) → **harness engineer** (fast, deterministic,
deep-reaching) → **coverage coach** (clear the wall the engine is stuck behind — the biggest perf lever) →
**crash analyst**. Detection is always the engine's job, never any hat's.

## Helper tooling (deterministic, in this repo)

- `python3 scripts/scan_targets.py <repo>` — identify the fuzzing surface: candidate entry points where
  external data enters (tree-sitter if installed, regex heuristics otherwise). JSON output. *Not* a vuln
  scanner — it ranks where to point a fuzzer, not what is "buggy".
- `python3 scripts/mine_dict.py <repo> -o fuzz.dict` — mine a libFuzzer dictionary (magic bytes + string
  literals) from the target's source to get past format gates; pass it as `-dict=fuzz.dict`.
- `python3 scripts/collect_seeds.py <repo> -o out/corpus` — bootstrap a seed corpus from the repo's sample
  dirs + `*_seed_corpus.zip` (dedup, ≤5 MB, hash-named). One valid seed beats most flags.
- `bash scripts/run_fuzz.sh <build-dir> <out-dir> [seconds]` — build the Docker image and run the fuzzer with
  caps, mounting the output dir for corpus/crashes.
- `… /fuzzer -print_coverage=1 | python3 scripts/cover_gaps.py - --src /src` — rank uncovered / partly-covered
  target functions (frontier vs unreached) to drive the coverage-improvement loop.
- `templates/{cpp-libfuzzer,python-atheris,jvm-jazzer}/` — starting Dockerfile + harness per stack
  (C/C++ libFuzzer · Python Atheris · Java/JVM Jazzer).

Leave the generated harness + Dockerfile + a one-line re-run command in the repo so fuzzing becomes permanent.
