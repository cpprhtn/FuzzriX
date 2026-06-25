# Corpus management

A corpus is the fuzzer's memory: the set of interesting inputs that drive coverage. A good seed corpus and a
corpus that survives across runs is often the single biggest lever on bug-finding — far more than run time.
This leaf covers three things, all in **one container, no cloud storage**:

1. **Seed** — fill the corpus from sample inputs before the run.
2. **Minimize** — `-merge=1` to dedup/shrink the corpus (drop inputs that add no coverage).
3. **Persist & reuse** — keep the corpus on a host-mounted volume so the next run starts where this one ended.

> This expands the "Seed the corpus" note in [fuzzing-run.md](fuzzing-run.md). The same `-rss_limit_mb` /
> `--memory` caps from [authorization.md](authorization.md) apply to every command here.

## The corpus directory lives on the host, not in the image

Mount one persistent dir per target and let it accumulate across runs. The container is throwaway; the corpus
is not. Never bake the corpus into the image (it goes stale and bloats layers) and never sync to a bucket —
the host volume *is* the persistence layer.

```bash
mkdir -p out/corpus out/crashes        # out/ is your persistent volume; reuse it every run
# ...then `docker run -v "$PWD/out:/out" ... /fuzzer ... /out/corpus`
```

## 1. Seed from sample inputs

Before the first run, copy any valid/sample inputs into the corpus dir. Look for `test/`, `tests/`,
`samples/`, `testdata/`, `corpus/`, `fixtures/`, example files, or anything whose format matches what the
harness parses. **One valid input often unlocks orders of magnitude more coverage than starting empty.**

```bash
# Copy candidate seeds in; flatten into the corpus dir (libFuzzer ignores subdir structure but be explicit).
find ./tests ./samples ./testdata -type f -size -5M 2>/dev/null \
  -exec cp -t out/corpus {} +     # cap at 5 MB/file (see size limit below)
```

If a seed bundle ships next to the target (e.g. a `*_seed_corpus.zip`), unpack it into the corpus dir **only
when the corpus is near-empty**, so you don't re-explode seeds over a corpus that's already grown.

| Seed rule | Value | Why |
|---|---|---|
| Unpack seed archive only if corpus has | ≤ 5 files | avoids re-seeding an already-grown corpus |
| Skip seed files larger than | 5 MB | oversized inputs slow exec/s and risk OOM |
| Name unpacked seeds | sequential `%016d` then re-hash on merge | deterministic, dedup-friendly |

No sample inputs anywhere? Start empty — libFuzzer will bootstrap — but say so in the report; an empty seed is
a disclosed weakness, not a silent one.

**Heavy domains live or die on the seed.** For crypto/TLS and media/codecs a cold start is nearly hopeless —
the format is too structured for the mutator to invent. Source real seeds: a few valid `.der`/`.pem` certs or
captured handshake records for TLS; a handful of tiny real `.mp4`/`.png`/`.ogg`/`.flac` files for a codec
(one per sub-format you enabled in the build). Projects onboarded to OSS-Fuzz ship a `*_seed_corpus.zip`
beside each fuzzer — use it. Keep each seed small (the ≤ 5 MB rule) and prefer many tiny valid inputs over a
few large ones, so a single mutation maps to one structural change.

## 2. Minimize the corpus with `-merge=1`

After a run (or any time the corpus grows), shrink it: `-merge=1` keeps the smallest set of inputs that
preserves total coverage and drops the rest. This is also how you fold newly-found inputs back into the
persistent corpus.

> Note: libFuzzer *already* trims corpus inputs during a normal fuzzing run — `-reduce_inputs` is **on by
> default (`=1`)** and shrinks an input whenever it can do so without losing any of its features. That is a
> per-input size reduction during fuzzing; `-merge=1` is a separate, whole-corpus dedup/minimization pass you
> run on demand. (There is also an experimental `-shrink` flag, **off by default (`=0`)**, that you do not
> need for a one-shot.) So even without ever running `-merge=1`, your corpus files stay reasonably small;
> `-merge=1` is what drops *redundant* inputs across the whole set.

**Exact command shape** (positional order matters: the **first** positional after the flags is the *output*
dir, the rest are *input* dirs merged into it — the output-dir-first order libFuzzer's `-merge` expects):

```bash
mkdir -p out/corpus_min
docker run --rm \
  --memory=2g --cpus=2 --pids-limit=512 --network=none \
  -e TMPDIR=/tmp/merge \
  -v "$PWD/out:/out" \
  fuzzrix-<target> \
  sh -c 'mkdir -p /tmp/merge && /fuzzer \
    -merge=1 \
    -rss_limit_mb=2048 \
    -timeout=25 \
    -max_len=5242880 \
    -artifact_prefix=/out/crashes/ \
    /out/corpus_min \
    /out/corpus'
# Merged, minimized corpus is now in /out/corpus_min. Swap it in:
# rm -rf out/corpus && mv out/corpus_min out/corpus
```

| Flag / arg | Value | Role in merge |
|---|---|---|
| `-merge=1` | — | turns the run into a corpus-minimization pass (no fuzzing) |
| **1st positional** | `/out/corpus_min` | **output** dir — minimized corpus is written here |
| **rest positionals** | `/out/corpus` (+ any extra dirs) | **input** dirs merged into the output |
| `-rss_limit_mb` | container RAM − overhead (here 2048 for `--memory=2g`) | merge loads inputs into memory; cap it or it OOMs |
| `-timeout` | 25 | per-input cap; a hanging input won't stall the whole merge |
| `-max_len` | 5242880 (5 MB) | enforce the per-input size limit during merge |
| `-artifact_prefix` | `/out/crashes/` | a corpus input can itself crash during merge — capture it |
| `TMPDIR` (env) | a writable dir | merge writes scratch/control files; point it at real space, not a tiny tmpfs |

> Note: `-rss_limit_mb=2048` here is derived from the local `--memory=2g` cap. Pick a value below your
> container's `--memory` and never raise the container cap just to make a merge fit.

**Timeout for the merge itself:** cap the whole `docker run` at a few minutes for a local one-shot — 5–10 min
is plenty (huge corpora might need 30, but that's not a one-shot). Merge runs **synchronously** — no cloud
queue, no distributed pruning.

**Bad inputs during merge.** If an input times out, OOMs, or crashes during merge, set it aside instead of
keeping it in the live corpus — quarantine it in a sibling dir (`out/quarantine/`) so it isn't re-fuzzed every
run. This is optional for a one-shot; do it if a run keeps re-tripping the same slow/OOM input.

## 3. Persist & reuse across runs

The corpus dir is mounted from the host, so it already survives container exit. Two rules keep reuse clean and
deduplicated **without any database or bucket**:

- **Content-address filenames by SHA1.** Name every corpus file after the SHA1 of its bytes. Identical inputs
  collide to one name → automatic dedup; merging two corpora is just a file move that skips names that already
  exist. libFuzzer already writes new finds under hash names; normalize any seeds you copy in.

  ```bash
  # Rename freshly-copied seeds to their content hash (so dedup + merge work uniformly):
  for f in out/corpus/*; do
    [ -f "$f" ] || continue
    h=$(sha1sum "$f" | cut -d' ' -f1)
    [ "$(basename "$f")" = "$h" ] || mv -n "$f" "out/corpus/$h"
  done
  ```

- **Merge new finds back, skipping what's already there.** When folding a run's new inputs into the persistent
  corpus, move only files whose SHA1 name isn't already present: a file whose basename is a 40-char hex SHA1
  *and* already exists is a duplicate → skip it. (Non-SHA1-named files are always moved, since their names
  aren't content-addressed.)

**Reuse loop across runs (the whole point):**

| Run | Corpus state |
|---|---|
| 1st | seed → fuzz (libFuzzer writes new finds into `/out/corpus`) → optional `-merge=1` minimize |
| 2nd | **same `/out/corpus`** mounted → fuzz resumes with all prior coverage → minimize |
| Nth | corpus only ever grows in coverage, stays small in size (merge prunes redundancy) |

Because step 2's command is identical to a fuzzing run with the *same* mounted `-v "$PWD/out:/out"` and the
same `/out/corpus` positional, **reuse is automatic** — just don't delete `out/corpus` between runs.

## Optional: corpus subset for a faster warm start

If the persistent corpus is large, the first seconds of a run are spent re-reading all of it. You can fuzz
from a random subset to cut startup time — new finds still merge back into the *full* corpus afterward. Pick a
fixed subset size (e.g. 100) and only subset when the corpus clearly exceeds it. Skip this in **quick** mode
(startup is already short); it's a **deep**-mode nicety, not required.

## Coverage delta from a merge (optional metric)

The single-step `-merge=1` above gives you the corpus's **total** `edge_coverage` / `feature_coverage`
(parsed from the merge log). To learn how many *new* edges/features **this run's** inputs added, run a
**two-step** merge: merge the old corpus alone for a baseline, then merge old+new and diff. (The two-step path
needs the target binary to support it; otherwise fall back to single-step totals.)

libFuzzer reports per-merge stats on a line you can parse from stderr:

```
MERGE-OUTER: <n> new files with <F> new features added; <E> new coverage edges
```

Capture `<F>` (→ `feature_coverage`) and `<E>` (→ `edge_coverage`); the two-step `new_edges` / `new_features`
are the difference between the second and first merge's totals. For a simple one-shot, the single-step merge
is fine and still gives `edge_coverage` / `feature_coverage` totals; report those as "the corpus now covers E
edges / F features."

> The two-step delta needs the merge control file from step 1 to persist into step 2 — extra plumbing in a
> hand-rolled shell one-shot, so prefer single-step totals unless you specifically need the per-run delta.
>
> To make the control file persist (instead of a throwaway temp file), pass `-merge_control_file=/out/merge.ctl`
> on the merge. libFuzzer also leaves this file in a resumable state if the merge is killed, so the same flag
> lets a long merge be restarted where it left off.

## Pitfalls

- **Don't bake the corpus into the image** — it goes stale and bloats layers. Mount it.
- **Don't skip `-rss_limit_mb` on merge** — merge loads the whole corpus; an uncapped merge OOM-kills the
  container instead of exiting cleanly. (And don't *raise* the container `--memory` to force a merge through.)
- **Don't merge with the output dir == an input dir** — write the minimized corpus to a fresh dir
  (`corpus_min`), verify it's non-empty, *then* swap it in. An empty output after merge means the merge
  failed; keep the old corpus.
- **Don't re-explode seeds over a grown corpus** — gate seed-unpack on the ≤ 5-files rule.
- **Per-input size cap** — keep corpus files ≤ 5 MB; pass `-max_len=5242880` on merge to enforce it.
