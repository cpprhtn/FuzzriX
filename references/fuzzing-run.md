# Fuzzing run

The image builds. Now run the fuzzer **with caps**, mount an output dir for corpus + crashes, and watch for
crashes / coverage plateau. Default to a short run; let the user opt into longer. Which knobs to turn (value
profile, dict, fork, max_len) is decided in [strategy-selection.md](strategy-selection.md); this leaf is how
you *launch* and *read* the run.

## Run it (libFuzzer, the MVP path)

`scripts/run_fuzz.sh` wraps this, but the shape is:

```bash
mkdir -p out/corpus out/crashes
# --name (not --rm): keep the container visible in `docker ps -a` after it exits.
docker run --name fuzzrix-<target>-run \
  --memory=2g --cpus=2 --pids-limit=512 --network=none \
  -v "$PWD/out:/out" \
  fuzzrix-<target> \
  /fuzzer \
    -max_total_time=120 \
    -rss_limit_mb=1536 \
    -timeout=25 \
    -print_final_stats=1 \
    -use_value_profile=1 \
    -artifact_prefix=/out/crashes/ \
    /out/corpus
```

`-print_final_stats=1` makes libFuzzer dump `stat::<name>: <value>` lines at the end — that's how you get
exec/s, peak RSS, and corpus growth out of the run (see *Metrics to extract* below). Always pass it.
`-use_value_profile=1` is FuzzriX's baseline (near-free extra coverage feedback — see
[strategy-selection.md](strategy-selection.md)).

**One entry point, every engine.** `run_fuzz.sh` always launches `/fuzzer`. C/C++ build the binary there
directly; Python (atheris) and Rust (cargo-fuzz) are also libFuzzer drivers, so a one-line `/fuzzer` wrapper
(atheris) or `cp` (cargo-fuzz) lets them reuse this exact path with the same flags. Go is the exception — its
native fuzzer is a separate runner; drive it directly (see *Engine variations* below).

### Flag reference

| Flag | Default | What it does |
| --- | --- | --- |
| `-max_total_time=<s>` | none (run forever) | Wall-clock cap. The most important flag — always set it. |
| `-timeout=<s>` | `25` — FuzzriX's choice; libFuzzer default is `1200` | Per-input limit. A single input exceeding this is written as `timeout-*` (hang / inf-loop bug). |
| `-rss_limit_mb=<n>` | `2560` — FuzzriX value; libFuzzer default is `2048` | Kill if RSS exceeds this; pairs with `--memory`. `0` = unlimited (don't use in a capped container). |
| `-artifact_prefix=<dir>/` | cwd | Where `crash-* / oom-* / timeout-* / leak-* / slow-unit-*` land. **Must** end with a trailing slash. |
| `-print_final_stats=1` | off | Emit `stat::` telemetry lines at exit. Always on. |
| `-use_value_profile=1` | off | Value-profile feedback (gets past `memcmp`/magic-number gates). FuzzriX baseline — near-free coverage. |
| `-dict=<file>` | none | Token dictionary (magic bytes, keywords). Big win for structured formats. |
| `-max_len=<n>` | auto (grows) | Cap input size. Leave unset for reproducibility; set a fixed value if the target is size-sensitive. |
| `-fork=<n>` | off | Parallel fuzzing processes. Cap at 2–4 in a container (don't use full CPU count); skip in quick mode. |
| `-runs=<n>` | unlimited | Stop after N inputs. Used for reproduction (`-runs=100`), not normal fuzzing. |
| last positional arg | — | Corpus dir(s). libFuzzer reads seeds and writes new interesting inputs back. |

**Keep `-rss_limit_mb` below `--memory`.** Reserve ~1 GB of headroom: pick an `rss_limit_mb` comfortably under
the `--memory` ceiling (for `--memory=2g` use `1536`; for `4g` use `~3072`). This makes libFuzzer
self-terminate with a clean `out-of-memory` artifact *before* Docker OOM-kills the container — a Docker
OOM-kill gives you no artifact and a non-clean exit.

**Run deterministically.** Large fuzzing fleets randomize `-max_len`, fork count, corpus subset, etc. per run
via a weighted strategy pool — that's for fleet-scale coverage, not reproducible one-shots. FuzzriX fixes
flags explicitly so a run can be re-run identically; pick them in
[strategy-selection.md](strategy-selection.md), don't randomize.

### If a target already ships a `.options` file

Some libFuzzer projects carry a sibling `<binary>.options` file (INI / ConfigParser format). **FuzzriX's
runner launches `/fuzzer` directly and does *not* parse `.options`** — that auto-merge is an orchestrator
behavior, not libFuzzer's. So if a target ships one, **read it and translate its keys into explicit CLI flags
/ ENV yourself**:

```ini
[libfuzzer]
timeout = 30
rss_limit_mb = 1024
max_len = 4096
dict = target.dict          ; path is relative to the .options file's directory

[asan]                       ; → fold into the ASAN_OPTIONS ENV (see dockerfile-generation.md)
detect_leaks = 1
```

- `[libfuzzer]` keys → `-key=value` on the command line (`dict` → `-dict=<resolved path>`; resolve `dict`
  relative to the `.options` file's directory, and **only** pass `-dict=` if the file exists — a missing dict
  makes libFuzzer exit `1`).
- `[asan] / [ubsan] / [msan]` keys → fold into the matching `*_OPTIONS` `ENV` line in the Dockerfile
  ([dockerfile-generation.md](dockerfile-generation.md#sanitizers)).
- Ignore `[env]` unless you understand it — only a tiny whitelist of keys there is meaningful.

## Seed the corpus

Copy any sample/valid inputs into `out/corpus` before launching — one valid seed often unlocks orders of
magnitude more coverage than starting empty. Seeding, `-merge=1` minimization, and reuse across runs are their
own phase: [corpus-management.md](corpus-management.md).

## Exit codes — classify the run outcome

| Return code | Meaning | FuzzriX action |
| --- | --- | --- |
| `0`, `72`, `-15` | Clean exit (`72` = libFuzzer interrupt, `-15` = SIGTERM at time cap) | Normal end. Check log for crash artifacts anyway. |
| `77` | **Bug found in the target** (sanitizer / libFuzzer crash) | Crash. Collect artifact, go to triage. |
| `70`, `71` | **libFuzzer timeout (`70`) or OOM (`71`)** — libFuzzer's own exit codes (`-timeout_exitcode=70`; OOM is hardcoded `71`), seen when the sanitizer's `exitcode=77` is *not* forced. | Crash. Collect the `timeout-*`/`oom-*` artifact, go to triage. |
| `1` | **libFuzzer error** (e.g. bad `-dict`, bad flag) — not a target bug | Fix the invocation/dict, re-run. Not a finding. |
| other, no `Test unit written to` in log, no `INITED` line | **Startup crash** (target/build broken) | Report build/instrumentation issue, do not count as a fuzzing crash. |

Force the sanitizer's `exitcode=77` (e.g. `ASAN_OPTIONS=...:exitcode=77`) so sanitizer crashes surface as `77`
and are unambiguous (see [dockerfile-generation.md](dockerfile-generation.md#sanitizers)).

## What to watch — libFuzzer stderr vocabulary

libFuzzer logs progress as `#<N> <KEYWORD>` lines (`READ`, `INITED`, `NEW`, `pulse`, `REDUCE`, `RELOAD`,
`DONE`). The ones that matter:

| Line | Meaning |
| --- | --- |
| `#N INITED ...` | Engine initialized successfully. **No `INITED` + non-zero exit = startup crash**, not a fuzzing crash. |
| `#N NEW ...` | New coverage found; corpus is growing. Rate of `NEW` = exploration health. |
| `#N REDUCE ...` | Found a smaller input for the same coverage (good, corpus tightening). |
| `#N pulse ...` | Periodic heartbeat with running cov/exec-s/rss — your live throughput signal. |
| `#N RELOAD ...` | Re-reading the corpus dir (e.g. fork/parallel sync). |
| `Done N runs ...` | Run finished cleanly. |
| `cov: <n> ft: <n> ... exec/s: <n> rss: <n>Mb` | Inline metrics on `pulse`/`INITED`/`NEW` lines. Rising `cov`/`ft` = good; flat for a long stretch = plateau. |

Startup / instrumentation sanity (check these first):

- `INFO: Loaded N PC tables (M PCs):` — instrumentation present; the parenthesized count is the total
  instrumented PCs (the `edges_total` denominator for `cov:`). Its absence (or a near-zero count) means the
  target was not built with coverage instrumentation.
- `ERROR: ... Is the code instrumented for coverage?` — **bad instrumentation.** Abort and rebuild the target
  with `-fsanitize=fuzzer` (this is a build failure, not a fuzzing failure).
- `INFO: seed corpus: files: N ... rss: NMb` — seeds loaded. If this appears but no `INITED`/`pulse`/`Done`
  follows, the corpus itself crashed the target on load (a corpus crash).
- `Dictionary: N entries` — confirms `-dict` was actually parsed and used.

## Crash type — classify by artifact name + log line

libFuzzer names the artifact by category; this is the deterministic signal (the exit code only tells you
*that* it crashed). Scan stderr for `Test unit written to <path>`:

| Artifact / log line | Category | Notes |
| --- | --- | --- |
| `crash-<hash>` | crash | Generic sanitizer error / SEGV / assert. |
| `oom-<hash>` or `ERROR: libFuzzer: out-of-memory` | OOM | Hit `-rss_limit_mb`. Resource issue, not usually a security bug. |
| `timeout-<hash>` or `ERROR: libFuzzer: timeout` | hang | Single input exceeded `-timeout`. Possible inf-loop / algorithmic-complexity bug. |
| `ERROR: LeakSanitizer` | leak | Memory leak (only if `detect_leaks=1`). |
| `slow-unit-<hash>` | slow unit | **Not a crash** — flags a perf-sensitive path. Count and report, keep fuzzing. |

The crash-path capture only recognizes the four crash categories: extract it with the regex
`Test unit written to\s*(.*(crash|oom|timeout|leak)-.*)` — group 1 is the file you hand to triage. A
`slow-unit-*` line is detected separately and is **not** returned as a crash path.

## Metrics to extract (from `-print_final_stats=1`)

Parse the trailing `stat::<name>: <value>` lines (regex `stat::([A-Za-z_]+):\s*(\S+)`; libFuzzer only emits
integer values). The stats libFuzzer actually prints are:

| Stat / derived | Source | Use |
| --- | --- | --- |
| exec/s | `stat::average_exec_per_sec` (or read off `pulse`) | Primary throughput. `<100/s` ⇒ harness does too much per call (I/O, allocs). |
| total executions | `stat::number_of_executed_units` | How many inputs ran this session. |
| peak RSS | `stat::peak_rss_mb` | Memory pressure. If it nears `-rss_limit_mb`, expect OOM. |
| corpus growth | `stat::new_units_added` | New interesting inputs added this run. |
| slowest unit | `stat::slowest_unit_time_sec` | Perf outlier; rising values hint at a slow path. |
| coverage | final `cov:` / `ft:` on the last `pulse`/`INITED` line | Growth vs. `edges_total` = how much of the target you reached. (Not a `stat::` value — read it off the log; precise edge/feature totals come from a separate merge pass — see [corpus-management.md](corpus-management.md).) |
| time-to-first-crash | run duration when the first `Test unit written to` appears | Report `time_to_first_crash_seconds`; `N/A` if no crash. |
| seed corpus size | `INFO: seed corpus: files: N` line | Starting corpus quality. |

These are the machine-readable numbers behind the README's "evaluable by design" claim — emit them with the report.

> **Coverage is reported differently per engine.** Only native libFuzzer (C/C++ and Rust cargo-fuzz) prints
> `cov:`/`ft:`. **atheris** prints only `corp: N/...` (no `cov:` number) and **Go**'s native fuzzer reports
> `new interesting: N (total: M)`. So when `cov:` is absent, fall back to the corpus/interesting-input count
> as a coverage *proxy* — don't report `cov` as 0/None and call the run dead. Also: atheris only instruments
> *Python* code — a native C extension (e.g. `ujson`) stays a black box and the corpus barely grows unless the
> extension itself is built with coverage (see [harness-generation.md](harness-generation.md#python-atheris)).

## Engine variations

The libFuzzer path above is the MVP. The other engines use their own runners:

- **AFL++**: `afl-fuzz -i out/corpus -o out/findings -- /fuzzer @@` (file input) — crashes land in
  `out/findings/default/crashes/`. Set `AFL_*` env and `-V <seconds>` for a time cap.
- **Atheris**: `python3 harness.py -max_total_time=120 out/corpus` — same libFuzzer flags (the `/fuzzer`
  wrapper makes this drop into the MVP path).
- **cargo-fuzz**: `cargo fuzz run <name> -- -max_total_time=120` — crashes in `fuzz/artifacts/<name>/`.
- **Go**: `go test -fuzz=FuzzX -fuzztime=120s` — failing inputs in `testdata/fuzz/FuzzX/` (not a libFuzzer
  binary; does not accept the flags above).

## Stop conditions

Stop when: time cap hits (`Done N runs`), a crash is found (in quick mode), coverage plateaus for a long
stretch (no `NEW`/rising `cov` for a sustained window), exit code is `77`/non-zero, or the user says so. On a
startup crash (no `INITED`) or bad-instrumentation error, stop immediately and surface the build problem. Then
collect the crash artifacts and go to [crash-triage.md](crash-triage.md).
