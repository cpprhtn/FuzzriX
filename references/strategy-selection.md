# Strategy selection

Before you launch, decide **which libFuzzer knobs to turn**. Large fuzzing fleets randomize these from a
weighted pool (a bandit picks per-run, amortized over millions of runs). FuzzriX is a **one-shot,
reproducible** run, so the `strategy_selector` instead makes a **deterministic, justified** choice per target
and **emits the rationale** — a strategy is only useful here if you can say *why* and re-run it identically.

> **Reproducibility over randomness.** A fleet's value is *aggregate* exploration; ours is *one* run a user
> can re-run and trust. So: fix values (don't sample `-max_len` randomly), pick strategies by target shape (not
> by dice), and write the choice + reason into the report. Randomized strategies are opt-in, never the default.

## The catalog (libFuzzer)

Every realistic strategy is a **flag on the stock libFuzzer binary** or a **filesystem move** — nothing that
needs cloud infra or a custom-built engine.

| Strategy | How it's applied | FuzzriX take |
|---|---|---|
| **value_profile** | `-use_value_profile=1` | **On by default** (libFuzzer ships it *off*; FuzzriX flips it on). Tracks interesting compared values (e.g. `memcmp`/magic-number checks) to get past hard equality gates. In ablation it was the **most consistent win** — it lifts *feature* coverage substantially on gated parsers (often the single biggest knob). Not free: libFuzzer documents up to ~2x slowdown and the corpus can grow several times — worth it for parsers/decoders, drop it if exec/s tanks on a hot target. Needs `-fsanitize-coverage=trace-cmp` (on by default as part of `-fsanitize=fuzzer`). |
| **recommended_dict** | `-dict=<file>` | **A small consistent help; a *huge* win behind a string/magic gate.** A token dictionary (magic bytes, keywords) gives the largest lift when the target gates on **specific strings/magics** (`memcmp(data,"MAGIC",..)`) — there it's the difference between reaching the bug or not. On formats already built from common punctuation (JSON `{}[]:,"`) the win is smaller but **still positive** (a 3-trial ablation on cJSON measured +~5% features with a dict; an earlier *single*-trial run wrongly looked negative — single trials are noise, see Discipline). So: always worth applying when a dict exists or is cheap to mine; prioritize synthesizing one when you see a string/magic gate. Look for `<binary>.dict` beside the target; else mine string/byte literals. Validate the file exists before passing the flag — stock libFuzzer errors on a missing dict. |
| **fixed max_len** | `-max_len=<N>` | **Fix it, don't randomize.** Pin a single `-max_len` (e.g. the format's realistic max, or 4096) so the run is reproducible. Omit entirely to let libFuzzer auto-grow. |
| **corpus_subset** | pass a *subset dir* as the corpus arg (no flag) | **Only if the corpus is large.** Pick one fixed size (e.g. 100) and only subset when the corpus clearly exceeds it — faster startup, less I/O. New finds still merge back. No-op for a small/empty corpus. |
| **fork** | `-fork=<N>` | **standard/deep only, capped to `--cpus`.** Parallel fuzzing processes. Pin a deterministic, capped `N = min(--cpus, 4)` — never the host core count (it would blow the container's CPU cap). Off in quick mode for fast startup. |
| **entropic** | `-entropic=1` | **Leave on — it's the default and it's deterministic.** A coverage-aware power schedule that mutates corpus inputs hitting *rare* features more often. No flag needed and no resource cost. It stays reproducible under a fixed run: the one knob that would break determinism is `-entropic_scale_per_exec_time=1` (off by default; scales schedule by exec time → non-deterministic even with a fixed `-seed`), so **never enable it**. Setting `-focus_function` also disables entropic — don't. |

### Marked unrealistic — do NOT propose these

| Strategy | Why it's out of scope for FuzzriX |
|---|---|
| **radamsa / external mutators** | Requires a **custom-patched mutator** (`libradamsa.so`) baked into the engine and wired as an external mutator. FuzzriX builds a **stock** libFuzzer binary in a one-shot container; patching in a mutator is engine surgery, not a runtime flag. Skip it. |
| **ML / RL-guided mutators** (learned `-custom_mutator`, model-in-the-loop input generation) | Needs a trained model, extra infra, and a non-deterministic generator. It also violates the core thesis — **the deterministic engine finds bugs, the LLM does not generate inputs.** Out of scope. |
| **weighted strategy pool / multi-armed bandit** | Cloud-only: it amortizes random choices over millions of distributed runs. A single capped run can't benefit; we choose deterministically instead. |

## FuzzriX strategy matrix by mode

Keyed to the SKILL.md modes (quick / standard / deep). `-use_value_profile=1` and a dict (when available) are
the constant baseline; the rest scale with depth.

| Knob | quick (≈60s) | standard (default) | deep (CI / long) |
|---|---|---|---|
| `-use_value_profile=1` | ✅ on | ✅ on | ✅ on |
| `-dict=<file>` | ✅ if it already exists | ✅ exists **or** generate one | ✅ generate + refine |
| `-max_len` | omit (auto) | fixed if format has a natural cap | fixed |
| corpus_subset | ✗ (seed corpus is small) | ✅ if corpus clearly exceeds the subset size | ✅ if corpus clearly exceeds the subset size |
| `-fork=N` | ✗ (fast startup) | `N=min(--cpus,2)` | `N=min(--cpus,4)` |

Folded into the run command from [fuzzing-run.md](fuzzing-run.md), a standard-mode invocation looks like:

```bash
/fuzzer \
  -max_total_time=120 -rss_limit_mb=2048 -timeout=25 \
  -artifact_prefix=/out/crashes/ \
  -use_value_profile=1 \
  -dict=/out/target.dict \
  /out/corpus
# deep mode adds: -fork=2   (N = min(--cpus, 4))
```

Fork **must** stay inside the resource gate: `-fork=N` with `N ≤ --cpus` (see
[authorization.md](authorization.md) — cap everything before launch).

## What the strategy_selector emits

The selector's output is **a strategy + its rationale**. Keep it small and machine-readable so it lands in the
run metrics. Tie the rationale to the target's *shape*, not to chance:

```json
{
  "mode": "standard",
  "flags": ["-use_value_profile=1", "-dict=/out/target.dict", "-max_len=4096"],
  "fork": 0,
  "corpus_subset": null,
  "rationale": {
    "value_profile": "target does magic-number + length checks (memcmp on a 4-byte header) — value profile gets past them",
    "dict": "generated from 11 string/byte literals found in parse_header(); structured binary format",
    "max_len": "fixed at 4096 (format's max record size) for reproducibility instead of a random length",
    "fork": "off in standard mode for fast startup",
    "skipped": {
      "radamsa": "needs a patched mutator baked into the engine — out of scope for a stock one-shot build",
      "ml_mutator": "no deterministic engine support; LLM does not generate inputs (core thesis)"
    }
  }
}
```

Map the rationale to the README's strategy axes where it helps the reader: **raw-bytes** (no dict, just
value_profile) · **dictionary** (`-dict`) · **structure-aware** (dict + a structured harness) · the
differential/stateful axes are harness-shape decisions, not libFuzzer flags — note them but resolve them in
[harness-generation.md](harness-generation.md).

## Discipline

- **Justify or drop.** A flag with no rationale doesn't go in the command — an unexplained knob is noise, and
  the report has to say *why* each strategy is on.
- **Reproducible by default.** Fix `-max_len`; don't randomize. Randomized strategies are opt-in and must be
  flagged as non-reproducible in the report.
- **Never break the cap.** `-fork=N ≤ --cpus`; `-rss_limit_mb` ≤ `--memory` minus overhead. A strategy that
  blows the resource gate is a bug, not a strategy.
- **Don't fake a strategy.** Enabling `-dict` with a missing file, or claiming a sanitizer/leak knob the build
  doesn't actually have, is a no-op that still gets reported as "on" — that's a fabricated pass. Validate first.
- **Compare over repeats, not one run.** Fuzzing is stochastic: a single timed run's `cov`/`ft` count swings
  several percent between *identical* runs (a fixed `-seed` doesn't remove thread/timing nondeterminism). That
  swing is enough to flip a strategy verdict — a single-trial ablation made a dict look *negative* on cJSON;
  over 3 trials (median) it was clearly positive. So before concluding a knob helps or hurts, run each config
  **≥3 times and take the median**. Never tune a strategy off one number.

Strategy chosen → build & heal ([self-healing.md](self-healing.md)) → run with these flags
([fuzzing-run.md](fuzzing-run.md)).
