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

`profile → identify fuzzing surface → synthesize strategy + harness + Dockerfile → build & self-heal →
fuzz (deterministic engine) → analyze crashes (root cause + fix + regression test) & report`

## Helper tooling (deterministic, in this repo)

- `python3 scripts/scan_targets.py <repo>` — identify the fuzzing surface: candidate entry points where
  external data enters (tree-sitter if installed, regex heuristics otherwise). JSON output. *Not* a vuln
  scanner — it ranks where to point a fuzzer, not what is "buggy".
- `bash scripts/run_fuzz.sh <build-dir> <out-dir> [seconds]` — build the Docker image and run the fuzzer with
  caps, mounting the output dir for corpus/crashes.
- `templates/cpp-libfuzzer/` — starting Dockerfile + harness for C/C++ libFuzzer.

Leave the generated harness + Dockerfile + a one-line re-run command in the repo so fuzzing becomes permanent.
