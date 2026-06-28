#!/usr/bin/env python3
"""FuzzriX seed-corpus collector.

A good seed corpus is the cheapest way to get a fuzzer past format gates and deep
into a target — often worth far more than any flag (see references/corpus-management.md;
the Magma libpng run showed a palette/chunk seed was the difference). This is the
deterministic half of "seed the corpus": the agent points it at the target repo,
it gathers real sample inputs, and the engine starts from them.

What it does (the corpus-management discipline, as code):
  - walk the usual sample dirs (test*/ samples/ testdata/ fixtures/ corpus/ … ) and
    pull data files — skipping source/build/doc files that aren't fuzz inputs;
  - unpack any `*_seed_corpus.zip` (the OSS-Fuzz convention) and other `*.zip`;
  - keep only inputs in (1 .. --max-size, default 5 MB) bytes;
  - dedup by content hash and write each seed under its **sha256 name** (flat,
    deterministic, merge-friendly) into the output corpus dir, capped at --max.

With `--ext png,json` it instead matches those extensions anywhere in the repo
(use when the format is known). Output is a ready `-` corpus dir for run_fuzz.sh.

Usage:
    python3 collect_seeds.py <repo> -o out/corpus            # auto from sample dirs
    python3 collect_seeds.py <repo> -o out/corpus --ext png,jpg
    python3 collect_seeds.py <repo> --dry-run --pretty       # list, don't copy
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

SEED_DIRS = {"test", "tests", "testdata", "test_data", "samples", "sample",
             "corpus", "corpora", "fixtures", "fixture", "examples", "example",
             "data", "inputs", "seeds", "seed", "regress", "regression"}
SKIP_DIRS = {".git", "build", "out", "node_modules", "cmake-build-debug", "__pycache__"}
# Extensions that are source / build / doc — not fuzz inputs. Used only when --ext
# is not given (a file with one of these, or a test *code* file, is skipped).
_NOT_INPUT_EXT = {
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".inc",
    ".py", ".rs", ".go", ".java", ".kt", ".scala", ".js", ".ts", ".rb", ".php",
    ".lua", ".pl", ".sh", ".bash", ".ps1", ".m", ".swift",
    ".cmake", ".mk", ".mak", ".am", ".in", ".ac", ".toml", ".cfg", ".ini",
    ".gradle", ".bazel", ".bzl", ".gn", ".gni", ".pc", ".map",
    ".md", ".rst", ".adoc", ".gitignore", ".gitkeep", ".gitattributes",
    ".o", ".a", ".so", ".dylib", ".lo", ".la", ".pyc",
}
_MAX_SIZE_DEFAULT = 5 * 1024 * 1024
_MAX_SEEDS_DEFAULT = 256


def _iter_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and not any(part in SKIP_DIRS for part in p.parts):
            yield p


def _in_seed_dir(p: Path, root: Path) -> bool:
    rel = p.relative_to(root)
    return any(part.lower() in SEED_DIRS for part in rel.parts[:-1])


def _looks_like_input(p: Path) -> bool:
    # a data file, not source/build/doc; no-extension files (hash-named corpus) count
    return p.suffix.lower() not in _NOT_INPUT_EXT


def collect(root: Path, *, exts: "set[str] | None" = None, unpack_zip: bool = True,
            max_size: int = _MAX_SIZE_DEFAULT, max_seeds: int = _MAX_SEEDS_DEFAULT):
    """Return {sha256: bytes} of accepted seeds, plus a stats dict."""
    seeds: dict[str, bytes] = {}
    stats = {"scanned": 0, "from_zip": 0, "too_big": 0, "empty": 0, "skipped_kind": 0}

    def offer(data: bytes, from_zip: bool = False):
        stats["scanned"] += 1
        if not data:
            stats["empty"] += 1
            return
        if len(data) > max_size:
            stats["too_big"] += 1
            return
        seeds.setdefault(hashlib.sha256(data).hexdigest(), data)
        if from_zip:
            stats["from_zip"] += 1

    for p in _iter_files(root):
        if exts is not None:
            if p.suffix.lower().lstrip(".") in exts:
                try:
                    offer(p.read_bytes())
                except OSError:
                    pass
            continue
        # auto mode: zips anywhere, data files inside sample dirs
        if unpack_zip and p.suffix.lower() == ".zip" and (
                "seed_corpus" in p.name or _in_seed_dir(p, root)):
            try:
                with zipfile.ZipFile(p) as z:
                    for info in z.infolist():
                        if not info.is_dir() and info.file_size <= max_size:
                            offer(z.read(info), from_zip=True)
            except (zipfile.BadZipFile, OSError):
                pass
            continue
        if _in_seed_dir(p, root) and _looks_like_input(p):
            try:
                offer(p.read_bytes())
            except OSError:
                pass
        else:
            if _in_seed_dir(p, root):
                stats["skipped_kind"] += 1

    # cap: keep the smallest N (small seeds = more mutation budget per corpus-management)
    if len(seeds) > max_seeds:
        keep = sorted(seeds.items(), key=lambda kv: len(kv[1]))[:max_seeds]
        seeds = dict(keep)
    return seeds, stats


def write_corpus(seeds: dict, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for h, data in seeds.items():
        (out / h).write_bytes(data)   # content-hash name: flat, dedup-friendly
    return len(seeds)


def _main(argv: "list[str] | None" = None) -> int:
    p = argparse.ArgumentParser(prog="collect_seeds.py", description="Bootstrap a seed corpus from a repo.")
    p.add_argument("repo")
    p.add_argument("-o", "--out", help="corpus dir to write seeds into (named by content hash)")
    p.add_argument("--ext", help="comma list (png,jpg): match these extensions anywhere, instead of sample dirs")
    p.add_argument("--max", type=int, default=_MAX_SEEDS_DEFAULT, help="cap seed count (default 256)")
    p.add_argument("--max-size", type=int, default=_MAX_SIZE_DEFAULT, help="skip files larger than this (bytes, default 5MB)")
    p.add_argument("--no-zip", action="store_true", help="don't unpack *_seed_corpus.zip")
    p.add_argument("--dry-run", action="store_true", help="don't write; just report")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args(argv)

    root = Path(args.repo)
    if not root.exists():
        print(f"error: path not found: {root}", file=sys.stderr)
        return 2
    exts = {e.strip().lower().lstrip(".") for e in args.ext.split(",")} if args.ext else None
    seeds, stats = collect(root, exts=exts, unpack_zip=not args.no_zip,
                           max_size=args.max_size, max_seeds=args.max)

    if not args.dry_run and args.out:
        n = write_corpus(seeds, Path(args.out))
        print(f"wrote {n} seeds → {args.out}", file=sys.stderr)
    if args.pretty or args.dry_run or not args.out:
        sizes = sorted(len(d) for d in seeds.values())
        print(f"{len(seeds)} unique seeds  "
              f"(from_zip={stats['from_zip']}, too_big={stats['too_big']}, "
              f"skipped_non_input={stats['skipped_kind']})")
        if sizes:
            print(f"  size bytes: min={sizes[0]} median={sizes[len(sizes)//2]} max={sizes[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
