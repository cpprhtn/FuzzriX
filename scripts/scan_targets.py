#!/usr/bin/env python3
"""FuzzriX target-function scanner.

Find and rank functions that ingest external/attacker-controlled data and are therefore good fuzz targets.
Uses tree-sitter for accurate C/C++ signatures when its bindings are installed; falls back to regex
heuristics otherwise. Output is JSON the agent can read to pick targets.

Usage:
    python3 scan_targets.py <repo> [--lang c|cpp|auto] [--top N] [--json|--pretty]

The score is a *starting* rank — the agent should apply reachability judgment on top.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

C_EXTS = {".c", ".h"}
CPP_EXTS = {".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"}
ALL_EXTS = C_EXTS | CPP_EXTS

SKIP_DIRS = {".git", "build", "out", "node_modules", "third_party", "vendor", "test", "tests",
             "deps", "external", "cmake-build-debug", "cmake-build-release", ".cache"}

# --- scoring heuristics ------------------------------------------------------

# (regex on the signature, points, reason)
SIG_SIGNALS = [
    (re.compile(r"\bconst\s+(unsigned\s+char|uint8_t|u8)\s*\*\s*\w+\s*,\s*\w*\s*(size_t|size|len)\b"), 50,
     "takes (const uint8_t*, size_t) — already libFuzzer-shaped"),
    (re.compile(r"\b(uint8_t|unsigned char|char|void)\s*\*\s*\w+\s*,\s*[^,)]*\b(size_t|size|len|n|count)\b"), 30,
     "takes a buffer + length"),
    (re.compile(r"\bFILE\s*\*"), 18, "takes a FILE*"),
    (re.compile(r"\bstd::string\b|\bchar\s*\*\s*\w*(path|file|name|expr|input|text|data|query|str|buf|json|xml|yaml|src|msg)", re.I), 16, "takes a string/input"),
    (re.compile(r"\bstd::(vector|span)\s*<\s*(uint8_t|unsigned char|char|std::byte)"), 22, "takes a byte vector/span"),
    (re.compile(r"\bvoid\s*\*\s*\w+\s*,\s*[^,)]*\bsize"), 20, "takes (void*, size)"),
]

# (regex on the function name, points, reason)
NAME_SIGNALS = [
    # (?:\b|_) so a CamelCase/snake API name (cJSON_Parse, png_read_info) still matches,
    # not just a leading-word match.
    (re.compile(r"(?:\b|_)(parse|decode|deserialize|unpack|unmarshal)\w*", re.I), 26, "parser/decoder name"),
    (re.compile(r"(?:\b|_)(read|load|import|scan|consume)\w*", re.I), 14, "input-reader name"),
    (re.compile(r"\w*(handler|process|dispatch)\b", re.I), 12, "handler/processor name"),
    (re.compile(r"\w*(packet|frame|header|message|record|chunk|token)\w*", re.I), 12, "protocol/format unit in name"),
    (re.compile(r"\b(from_bytes|from_buffer|from_string|fromjson|fromxml)\w*", re.I), 22, "from-bytes constructor"),
]

# unsafe primitives in the body (read separately per function span)
BODY_SIGNALS = [
    (re.compile(r"\b(memcpy|memmove|strcpy|strcat|sprintf|vsprintf|alloca|gets)\s*\("), 16,
     "calls unsafe memory primitive"),
    (re.compile(r"\bmalloc\s*\(\s*[^)]*\b(len|size|n|count)\b"), 14, "allocates a size derived from input"),
    (re.compile(r"\[\s*\w+\s*[-+]\s*\d+\s*\]"), 6, "manual index arithmetic"),
]

# crude C/C++ function-definition matcher for the regex fallback
FUNC_DEF_RE = re.compile(
    r"^[ \t]*"
    r"(?:(?:static|inline|extern|EXPORT|__attribute__\([^)]*\)|[A-Z][A-Z0-9_]*API)\s+)*"  # qualifiers
    r"(?P<ret>"
    r"(?:[A-Z][A-Z0-9_]*\s*\([^()]*\)\s+)"      # export-macro wrapping the return type: CJSON_PUBLIC(cJSON *)
    r"|[A-Za-z_][\w:<>,\s\*&]*?[\s\*&]"          # OR a plain return type
    r")"
    r"(?P<name>[A-Za-z_]\w*)\s*"                                                            # name
    r"\((?P<args>[^;{]*?)\)\s*"                                                             # args
    r"(?:const\s*)?(?:noexcept\s*)?\{",                                                     # opening brace
    re.MULTILINE,
)

KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "do", "else", "case"}


def iter_source_files(root: Path, exts: set[str]):
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix in exts:
            yield p


def score_function(name: str, signature: str, body: str) -> tuple[int, list[str]]:
    score, reasons = 0, []
    for rx, pts, why in SIG_SIGNALS:
        if rx.search(signature):
            score += pts
            reasons.append(why)
    for rx, pts, why in NAME_SIGNALS:
        if rx.search(name):
            score += pts
            reasons.append(why)
            break  # one name reason is enough
    for rx, pts, why in BODY_SIGNALS:
        if rx.search(body):
            score += pts
            reasons.append(why)
    # an exported-looking name with no args is rarely a target
    if "(" in signature and signature.split("(", 1)[1].strip(") ") in ("", "void"):
        score -= 10
    # Internal memory-management plumbing (allocators) matches buffer/size signals
    # but isn't where *external* data enters — deprioritize.
    if re.search(r"(realloc|malloc|calloc|_alloc\b|dealloc|_free\b|free$)", name, re.I):
        score -= 20
        reasons.append("allocator/plumbing (deprioritized)")
    # Public (non-static) functions are the reachable API surface — the real entry
    # points; static helpers are only reached *through* them. Boost them.
    if not re.search(r"^\s*static\b|[\s*]static\b", signature):
        score += 10
        reasons.append("public API (external linkage)")
    return score, reasons


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def find_body(text: str, brace_idx: int, max_chars: int = 4000) -> str:
    """Return the function body from the opening brace, balanced, capped."""
    depth, i, n = 0, brace_idx, len(text)
    while i < n and i < brace_idx + max_chars:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[brace_idx:i + 1]
        i += 1
    return text[brace_idx:brace_idx + max_chars]


def scan_file_regex(path: Path) -> list[dict]:
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return []
    out = []
    for m in FUNC_DEF_RE.finditer(text):
        name = m.group("name")
        if name in KEYWORDS:
            continue
        signature = re.sub(r"\s+", " ", m.group(0).rstrip("{ \n\t")).strip()
        brace_idx = text.index("{", m.start("name"))
        body = find_body(text, brace_idx)
        score, reasons = score_function(name, signature, body)
        if score <= 0:
            continue
        out.append({
            "file": str(path),
            "line": line_of(text, m.start("name")),
            "name": name,
            "signature": signature[:240],
            "score": score,
            "reasons": reasons,
        })
    return out


def try_treesitter():
    """Return a (parser, language_for_ext) helper or None if tree-sitter isn't available."""
    try:
        from tree_sitter import Parser  # noqa: F401
        langs = {}
        try:
            import tree_sitter_c
            from tree_sitter import Language
            langs["c"] = Language(tree_sitter_c.language())
        except Exception:
            pass
        try:
            import tree_sitter_cpp
            from tree_sitter import Language
            langs["cpp"] = Language(tree_sitter_cpp.language())
        except Exception:
            pass
        if not langs:
            return None
        return langs
    except Exception:
        return None


def scan_file_treesitter(path: Path, langs) -> list[dict]:
    from tree_sitter import Parser
    lang_key = "c" if path.suffix in C_EXTS else "cpp"
    lang = langs.get(lang_key) or next(iter(langs.values()))
    try:
        src = path.read_bytes()
    except Exception:
        return []
    parser = Parser(lang)
    tree = parser.parse(src)
    out = []

    def text_of(node) -> str:
        return src[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def walk(node):
        if node.type == "function_definition":
            decl = node.child_by_field_name("declarator")
            body = node.child_by_field_name("body")
            name_node = None
            cur = decl
            # descend to the function_declarator's identifier
            while cur is not None:
                if cur.type in ("function_declarator",):
                    name_node = cur.child_by_field_name("declarator")
                    break
                nxt = cur.child_by_field_name("declarator")
                cur = nxt
            if name_node is not None:
                name = text_of(name_node).split("::")[-1]
                signature = re.sub(r"\s+", " ", text_of(decl)).strip()
                body_txt = text_of(body) if body else ""
                score, reasons = score_function(name, signature, body_txt[:4000])
                if score > 0 and name not in KEYWORDS:
                    out.append({
                        "file": str(path),
                        "line": name_node.start_point[0] + 1,
                        "name": name,
                        "signature": signature[:240],
                        "score": score,
                        "reasons": reasons,
                    })
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="FuzzriX target-function scanner")
    ap.add_argument("repo", help="path to the repository to scan")
    ap.add_argument("--lang", choices=["c", "cpp", "auto"], default="auto")
    ap.add_argument("--top", type=int, default=20, help="max candidates to emit")
    ap.add_argument("--pretty", action="store_true", help="human-readable instead of JSON")
    args = ap.parse_args(argv)

    root = Path(args.repo).expanduser().resolve()
    if not root.exists():
        print(f"error: {root} does not exist", file=sys.stderr)
        return 2

    exts = C_EXTS if args.lang == "c" else CPP_EXTS if args.lang == "cpp" else ALL_EXTS
    langs = try_treesitter()
    engine = "tree-sitter" if langs else "regex-heuristic"

    results: list[dict] = []
    for f in iter_source_files(root, exts):
        if langs:
            try:
                results.extend(scan_file_treesitter(f, langs))
            except Exception:
                results.extend(scan_file_regex(f))
        else:
            results.extend(scan_file_regex(f))

    # de-dup by (file, name, line), keep best score
    seen = {}
    for r in results:
        key = (r["file"], r["name"], r["line"])
        if key not in seen or r["score"] > seen[key]["score"]:
            seen[key] = r
    ranked = sorted(seen.values(), key=lambda r: r["score"], reverse=True)[:args.top]

    if args.pretty:
        print(f"# FuzzriX scan ({engine}) — {len(ranked)} candidate(s) in {root}\n")
        for r in ranked:
            print(f"[{r['score']:>3}] {r['name']}  ({r['file']}:{r['line']})")
            print(f"      {r['signature']}")
            print(f"      reasons: {', '.join(r['reasons'])}\n")
    else:
        print(json.dumps({"engine": engine, "root": str(root),
                          "count": len(ranked), "candidates": ranked}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
