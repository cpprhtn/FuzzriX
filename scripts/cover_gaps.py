#!/usr/bin/env python3
"""FuzzriX coverage-gap diagnoser — drive the coverage-improvement loop (the top
performance lever; see references/coverage-iteration.md).

A fuzzer run with `-print_coverage=1` dumps, per function:
    COVERED_FUNC:   hits: N edges: C/T  <func> <file>:<line>   # entered; C of T edges hit
    UNCOVERED_FUNC: hits: 0 edges: 0/T  <func> <file>:<line>   # never entered
This script turns that wall of text into "where to aim next":

  - **frontier** — functions you've *entered* but only partly covered (C<T),
    ranked by uncovered edges. You're already at the door; a seed/dict/value_profile
    nudge tends to unlock these cheaply. The highest-value place to push.
  - **unreached** — functions never entered, ranked by size (total edges). Big
    gated regions; need a new seed or a dictionary to get past whatever guards them.

Filter to the target's own source with `--src` so libc/system noise drops out.

Usage:
    /fuzzer -runs=N -print_coverage=1 2>&1 | python3 cover_gaps.py - --src /src
    python3 cover_gaps.py coverage.log --src src/ --top 15 --pretty
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# "<KIND>_FUNC: hits: N edges: C/T <func ...possibly spaces...> <file>:<line>"
_FUNC_RE = re.compile(
    r"^(?P<kind>COVERED|UNCOVERED)_FUNC:\s+hits:\s+(?P<hits>\d+)\s+"
    r"edges:\s+(?P<cov>\d+)/(?P<tot>\d+)\s+(?P<func>.+?)\s+(?P<file>\S+):(?P<line>\d+)\s*$")


@dataclass
class FuncCov:
    func: str
    file: str
    line: int
    hits: int
    covered_edges: int
    total_edges: int

    @property
    def uncovered_edges(self) -> int:
        return self.total_edges - self.covered_edges

    @property
    def entered(self) -> bool:
        return self.hits > 0

    def to_dict(self) -> dict:
        return {"func": self.func, "loc": f"{self.file}:{self.line}", "hits": self.hits,
                "edges": f"{self.covered_edges}/{self.total_edges}",
                "uncovered_edges": self.uncovered_edges}


def parse_coverage(text: str) -> list[FuncCov]:
    out = []
    for ln in text.splitlines():
        m = _FUNC_RE.match(ln)
        if m:
            out.append(FuncCov(
                func=m["func"].strip(), file=m["file"], line=int(m["line"]),
                hits=int(m["hits"]), covered_edges=int(m["cov"]), total_edges=int(m["tot"])))
    return out


def _in_src(fc: FuncCov, src: Optional[str]) -> bool:
    if not src:
        return True
    return src in fc.file


def analyze(funcs: list[FuncCov], src: Optional[str] = None, top: int = 20) -> dict:
    funcs = [f for f in funcs if _in_src(f, src)]
    frontier = sorted((f for f in funcs if f.entered and f.uncovered_edges > 0),
                      key=lambda f: f.uncovered_edges, reverse=True)
    unreached = sorted((f for f in funcs if not f.entered and f.total_edges > 0),
                       key=lambda f: f.total_edges, reverse=True)
    tot = sum(f.total_edges for f in funcs)
    cov = sum(f.covered_edges for f in funcs)
    return {
        "summary": {
            "functions": len(funcs),
            "entered": sum(1 for f in funcs if f.entered),
            "edge_coverage": f"{cov}/{tot}" + (f" ({100*cov//tot}%)" if tot else ""),
        },
        "frontier": [f.to_dict() for f in frontier[:top]],
        "unreached": [f.to_dict() for f in unreached[:top]],
    }


def _pretty(report: dict) -> str:
    s = report["summary"]
    out = [f"functions: {s['functions']}  entered: {s['entered']}  edges: {s['edge_coverage']}", ""]
    out.append("FRONTIER (entered, partly covered — push these first):")
    for f in report["frontier"]:
        out.append(f"  +{f['uncovered_edges']:>3} edges  {f['edges']:>7}  {f['func']}  ({f['loc']})")
    out.append("")
    out.append("UNREACHED (never entered — needs a new seed / dict to get past a gate):")
    for f in report["unreached"]:
        out.append(f"  {f['edges']:>6}  {f['func']}  ({f['loc']})")
    return "\n".join(out)


def _main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="cover_gaps.py", description="Diagnose coverage gaps from -print_coverage output.")
    p.add_argument("log", help="-print_coverage log ('-' for stdin)")
    p.add_argument("--src", help="only functions whose file path contains this (drop libc/system)")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args(argv)
    text = sys.stdin.read() if args.log == "-" else Path(args.log).read_text(errors="replace")
    report = analyze(parse_coverage(text), src=args.src, top=args.top)
    print(_pretty(report) if args.pretty else json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
