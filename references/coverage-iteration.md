# Coverage-driven iteration

FuzzriX can't win on **scale** — OSS-Fuzz runs fleets for weeks. It wins on **harness quality**. A first
harness typically reaches a small fraction of the target; the lever that closes the gap is a **bounded
feedback loop**: run briefly → read where the engine is stuck → remove that wall (harness / seed / dict / flag)
→ re-run. This is the single biggest performance multiplier in the skill.

> Wear the **coverage-coach** hat here. You are *not* hunting bugs by reading code — you are diagnosing why the
> deterministic engine isn't *reaching* interesting code, and clearing the obstacle. The engine still finds the
> bugs; you are widening its reach.

## When to iterate

After the first run — make it a short **smoke run** (~60s) so the signal is cheap. Iterate if any of:
coverage (`cov:`) plateaus early, only a small fraction of `edges_total` is hit, `exec/s` is poor, or whole
target functions are never entered. **Bounded, like self-heal:** default **2–3 rounds** (each a short run),
then one longer final run with the best harness. Stop when a round adds no coverage, or the wall is a genuine
limit you can only disclose (then record it — *cover it or flag it*).

## Read the coverage signal

| Signal | How to get it | Read |
|---|---|---|
| live coverage | `cov:` / `ft:` on `pulse` / `NEW` lines | `cov` = covered PCs, `ft` = features. rising = exploring; flat for a long window = **plateau** |
| total instrumented PCs | `INFO: Loaded N PC tables (M PCs):` at startup | the denominator: `cov:` / `M` ≈ fraction of the target reached (libFuzzer counts PCs; some tools label this `edges`) |
| which functions are unreached | a one-off run with `-print_coverage=1` | prints covered vs uncovered functions — **the named map of where the harness can't reach** |
| corpus-wide coverage | the `MERGE-OUTER` log line from a `-merge=1` pass (see [corpus-management.md](corpus-management.md)) | total feature / PC coverage of the whole corpus |

`-print_coverage=1` is the highest-signal tool: if the target's core parser/decoder functions show up
**uncovered**, the harness never reached them — that's your wall, named. (`-print_funcs=N` controls how many
are listed.) Its output is a wall of text, so pipe it through
**[`scripts/cover_gaps.py`](../scripts/cover_gaps.py)** to rank it into where to aim next:

```bash
docker run --rm fuzzrix-<t> /fuzzer -runs=20000 -print_coverage=1 2>&1 \
  | python3 scripts/cover_gaps.py - --src /src --pretty
```

It splits the functions into **frontier** (entered but partly covered, ranked by *uncovered edges* — you're at
the door, a seed/dict/value_profile nudge unlocks these cheaply) and **unreached** (never entered, ranked by
size — a big gated region needing a new seed/dict, or a sign the harness shape never calls that API). Push the
frontier first.

> **The payoff scales with target depth — diagnose before you iterate.** Measured: adding a rich seed round
> on a deep, many-function target (a recursive expression evaluator) roughly **doubled covered functions**
> (28 → 56); on a shallow single-entry parser (cJSON's `Parse`) the same round barely moved coverage — its
> first harness already reached the core. So `-print_coverage` first: if the core functions are already
> covered, don't spend rounds; if they're uncovered, a seed/dict/deeper-entry round is a big lever.

## Diagnose the wall → prescribe the fix

| Symptom | Likely wall | Fix (→ leaf) |
|---|---|---|
| `cov` plateaus almost immediately, tiny fraction of edges | harness only exercises shallow / wrapper code | call a **deeper entry point**, or split into several focused harnesses → [harness-generation.md](harness-generation.md) |
| `cov` flat, high `exec/s`, many runs, no `NEW` | stuck at a **magic-byte / checksum / length gate** | add dict tokens + a passing seed + `-use_value_profile=1`; if it's a checksum, build with `-DFUZZING_BUILD_MODE_UNSAFE_FOR_PRODUCTION` → [strategy-selection.md](strategy-selection.md), [dockerfile-generation.md](dockerfile-generation.md) |
| `exec/s` very low (<100) | harness too heavy per call | move setup into `LLVMFuzzerInitialize`, drop per-call I/O / allocs → [harness-generation.md](harness-generation.md) |
| nearly every input rejected (early `return` / `-1`), `cov` barely moves | front-door too strict / no valid seed | seed the corpus with a valid input; loosen the harness guard → [corpus-management.md](corpus-management.md) |
| coverage grows, then one input dominates the time budget | one huge / slow input | set a fixed `-max_len`; add `if (size > N) return 0;` → [strategy-selection.md](strategy-selection.md) |
| uncovered functions sit behind a mode / version flag | harness never sets that selector byte | carve a mode selector from the input with `FuzzedDataProvider` → [harness-generation.md](harness-generation.md) |

## The loop

```
run short (~60s) → read cov/ft, edges_total, and -print_coverage
round = 0
while round < MAX (default 3):
  if coverage is healthy and still rising:  break
  diagnose the wall (table above) → apply ONE fix (harness OR seed OR dict OR flag)
  if harness/Dockerfile changed: rebuild (self-heal if it breaks) → re-run short
  round += 1
final: one longer run with the best harness → triage
```

**One fix per round** — don't shotgun several at once or you lose the signal of which one helped (same
discipline as [self-healing.md](self-healing.md)). Every round stays inside the resource caps
([authorization.md](authorization.md)). If the wall can't be removed within the budget, record it in the ledger
as a **disclosed coverage limit** — e.g. *"reached ~18% of edges; the rest is behind an HMAC the harness can't
forge."* A known gap beats a silent one.

## Report

Emit final coverage as a metric (`cov` / `edges_total`, functions reached), the walls you removed, and any wall
you couldn't — these are part of the README's "evaluable by design" numbers and feed the
[fuzzing-run.md](fuzzing-run.md) metrics. When coverage is as deep as the budget allows and crashes are in
hand → [crash-triage.md](crash-triage.md).
