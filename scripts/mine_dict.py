#!/usr/bin/env python3
"""FuzzriX dictionary miner.

Build a libFuzzer/AFL++ dictionary from a target's own source — the tokens a
format gates on (magic strings, keywords, content-type literals) so the fuzzer
gets past `memcmp(data, "MAGIC", 5)`-style checks instead of brute-forcing them.
This is the deterministic half of strategy-selection's "synthesize/apply a dict":
the agent points it at the target, the engine uses the result.

What it extracts (deterministic, language-agnostic regex):
  - C/C++/Java/Rust/Go double-quoted string literals  "..."   (incl. \\xNN bytes)
  - char/byte arrays of hex magics                    {0x89,'P','N','G'}
  - obviously-gating literals near memcmp/strncmp/startswith/== comparisons
Then: unescape source escapes → re-escape to a valid dict value (only \\\\, \\",
\\xNN are legal — a raw control byte makes libFuzzer reject the WHOLE file), drop
too-short/too-long tokens, dedupe, and rank by a gate-proximity heuristic.

Usage:
    python3 mine_dict.py <repo-or-file> [-o out.dict] [--max N] [--min-len 2]
    python3 mine_dict.py <repo> --pretty        # human-readable, with reasons

Output is a ready-to-pass `-dict=` file (or JSON with --json). A dict is a hint,
not a guarantee — value_profile still does the heavy lifting (strategy-selection).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SRC_EXTS = {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx",
            ".java", ".rs", ".go", ".py"}
SKIP_DIRS = {".git", "build", "out", "node_modules", "third_party", "vendor",
             "test", "tests", "deps", "external", "fuzz", ".cache", "target"}

# A double-quoted literal, honoring backslash escapes (so we don't stop at \").
_STRING_RE = re.compile(r'"((?:\\.|[^"\\])*)"')
# Comparison/gate context that makes a nearby literal high-value.
_GATE_RE = re.compile(
    r"\b(memcmp|strncmp|strcmp|strncasecmp|memmem|startsWith|startswith|"
    r"equals|hasPrefix|HasPrefix|magic|MAGIC|signature|header)\b")
# A C byte-array of magics: hex {0x89,0x50}, chars {'P','N','G'}, or decimal
# {137,80,78,71}. Decimal-only arrays are accepted only in a signature context
# (below), since plain decimal arrays are usually lookup tables, not magics.
_BYTEARR_RE = re.compile(
    r"\{\s*((?:(?:0x[0-9a-fA-F]{1,2}|\d{1,3}|'(?:\\.|[^'])')\s*,?\s*){2,16})\}")
# A declaration that announces a magic/signature (gates the decimal-array case).
_SIG_CTX_RE = re.compile(r"\b\w*(sig|signature|magic|header|marker|bom|preamble)\w*\b", re.I)

_MIN_LEN_DEFAULT = 2
_MAX_LEN = 64            # libFuzzer truncates very long dict entries anyway
_MAX_TOKENS_DEFAULT = 200


def _unescape_source(s: str) -> bytes:
    """Turn a source string literal's body into the raw bytes it denotes
    (\\n -> 0x0a, \\xNN -> that byte, \\t, \\\\, \\\", octal \\NNN)."""
    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            simple = {"n": 0x0a, "r": 0x0d, "t": 0x09, "0": 0x00, "\\": 0x5c,
                      '"': 0x22, "'": 0x27, "a": 0x07, "b": 0x08, "f": 0x0c, "v": 0x0b}
            if n == "x":
                m = re.match(r"[0-9a-fA-F]{1,2}", s[i + 2:i + 4])
                if m:
                    out.append(int(m.group(0), 16))
                    i += 2 + len(m.group(0))
                    continue
            if n in simple:
                out.append(simple[n])
                i += 2
                continue
            out.append(ord(n) & 0xFF)   # unknown escape: take the char literally
            i += 2
            continue
        out.extend(c.encode("utf-8", "replace"))
        i += 1
    return bytes(out)


def dict_escape(raw: bytes) -> str:
    """Encode raw bytes as a libFuzzer dictionary value. Only \\\\, \\" and \\xNN
    are valid — a raw control byte (\\r, \\n, 0x89, ...) makes libFuzzer reject the
    whole dict (`ParseDictionaryFile: error in line N`). So emit non-printables as
    \\xNN. (Same rule as the harness codegen's dict_escape.)"""
    out = []
    for b in raw:
        if b == 0x5c:
            out.append("\\\\")
        elif b == 0x22:
            out.append('\\"')
        elif 0x20 <= b < 0x7f:
            out.append(chr(b))
        else:
            out.append(f"\\x{b:02x}")
    return "".join(out)


def _iter_source_files(root: Path):
    if root.is_file():
        yield root
        return
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in SRC_EXTS \
                and not any(part in SKIP_DIRS for part in p.parts):
            yield p


def _bytearray_to_raw(body: str) -> "bytes | None":
    """Decode a brace body to bytes. Returns None if any value is out of byte
    range (so a non-magic int array like {256, 1024} is rejected, not truncated)."""
    out = bytearray()
    for tok in re.findall(r"0x[0-9a-fA-F]{1,2}|\d{1,3}|'(?:\\.|[^'])'", body):
        if tok.startswith("0x"):
            out.append(int(tok, 16) & 0xFF)
        elif tok.isdigit():
            v = int(tok)
            if v > 255:
                return None
            out.append(v)
        else:
            out.extend(_unescape_source(tok[1:-1])[:1] or b"\x00")
    return bytes(out)


def mine(root: Path, *, min_len: int = _MIN_LEN_DEFAULT,
         max_tokens: int = _MAX_TOKENS_DEFAULT) -> list[dict]:
    """Return ranked dict entries: [{token, score, reason}]. `token` is already
    dict-escaped and ready to wrap in quotes."""
    scored: dict[bytes, tuple[int, str]] = {}

    def offer(raw: bytes, score: int, reason: str):
        if not (min_len <= len(raw) <= _MAX_LEN):
            return
        if raw.isdigit() if raw.isascii() else False:   # skip pure-number literals (noise)
            return
        prev = scored.get(raw)
        if prev is None or score > prev[0]:
            scored[raw] = (score, reason)

    for f in _iter_source_files(root):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for m in _STRING_RE.finditer(text):
            raw = _unescape_source(m.group(1))
            if not raw:
                continue
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            line = text[line_start:line_end if line_end != -1 else len(text)]
            gated = bool(_GATE_RE.search(line))
            offer(raw, 20 if gated else 8,
                  "string near a comparison/gate" if gated else "string literal")
        for m in _BYTEARR_RE.finditer(text):
            body = m.group(1)
            raw = _bytearray_to_raw(body)
            if not raw:
                continue
            decimal_only = "'" not in body and "0x" not in body.lower()
            if decimal_only:
                # Plain decimal arrays are usually lookup tables — only take one as
                # a magic if its declaration line announces a signature.
                ls = text.rfind("\n", 0, m.start()) + 1
                if not _SIG_CTX_RE.search(text[ls:m.start()]):
                    continue
            offer(raw, 18, "byte/magic array")

    ranked = sorted(scored.items(), key=lambda kv: (-kv[1][0], kv[0]))
    return [{"token": dict_escape(raw), "score": s, "reason": why}
            for raw, (s, why) in ranked[:max_tokens]]


def to_dict_file(entries: list[dict]) -> str:
    """Render entries as a libFuzzer dictionary file."""
    lines = ["# FuzzriX-mined dictionary (scripts/mine_dict.py)",
             "# format gates / magics extracted from target source"]
    lines += [f'"{e["token"]}"' for e in entries]
    return "\n".join(lines) + "\n"


def _main(argv: "list[str] | None" = None) -> int:
    p = argparse.ArgumentParser(prog="mine_dict.py", description="Mine a libFuzzer dictionary from target source.")
    p.add_argument("path", help="repo dir or single source file")
    p.add_argument("-o", help="write the .dict here (default: stdout)")
    p.add_argument("--max", type=int, default=_MAX_TOKENS_DEFAULT, help="max tokens (default 200)")
    p.add_argument("--min-len", type=int, default=_MIN_LEN_DEFAULT, help="min token bytes (default 2)")
    p.add_argument("--json", action="store_true", help="emit JSON (token/score/reason) instead of a .dict")
    p.add_argument("--pretty", action="store_true", help="human-readable listing with reasons")
    args = p.parse_args(argv)

    root = Path(args.path)
    if not root.exists():
        print(f"error: path not found: {root}", file=sys.stderr)
        return 2
    entries = mine(root, min_len=args.min_len, max_tokens=args.max)

    if args.json:
        out = json.dumps({"count": len(entries), "entries": entries}, indent=2)
    elif args.pretty:
        out = f"{len(entries)} tokens mined from {root}\n" + "\n".join(
            f'  [{e["score"]:>2}] "{e["token"]}"  — {e["reason"]}' for e in entries)
    else:
        out = to_dict_file(entries)

    if args.o:
        Path(args.o).write_text(out if out.endswith("\n") else out + "\n")
        print(f"wrote {len(entries)} tokens → {args.o}", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
