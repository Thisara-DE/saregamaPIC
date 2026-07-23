"""Phase 3.5 correction metrics and private-baseline evaluation helpers."""

import json
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

NOTE_RE = re.compile(r"[SRGMPDN](?:['_^,]*)")
TOKEN_RE = re.compile(r"[SRGMPDN](?:['_^,]*)|//|[|()+\-\[\]]|[^\s]")


def _stf_tokens(stf: dict[str, Any]) -> list[str]:
    header = stf.get("header", {})
    tokens = [
        f"header:concert:{header.get('concert_scale', '')}",
        f"header:alto:{header.get('alto_scale', '')}",
        f"header:beat:{header.get('beat', '')}",
    ]
    for line in stf.get("lines", []):
        tokens.append(f"line:{line.get('n')}:{line.get('kind', '')}")
        tokens.extend(TOKEN_RE.findall(str(line.get("text", ""))))
        tokens.append("<EOL>")
    return tokens


def _category(symbol: str) -> str:
    if symbol.startswith("header:"):
        return "header"
    if symbol.startswith("line:") or symbol == "<EOL>":
        return "layout"
    if symbol in {"(", ")"}:
        return "curve"
    if symbol in {"-", "+"}:
        return "rhythm"
    if symbol in {"|", "//"}:
        return "barline"
    if symbol in {"[", "]"}:
        return "layout"
    if NOTE_RE.fullmatch(symbol):
        if "_" in symbol or "^" in symbol:
            return "accidental"
        if "'" in symbol or "," in symbol:
            return "octave"
        return "letter"
    return "layout"


def correction_summary(raw_stf: dict[str, Any], corrected_stf: dict[str, Any]) -> dict[str, Any]:
    """Return privacy-preserving counts; never include the STF or token text."""
    raw = _stf_tokens(raw_stf)
    corrected = _stf_tokens(corrected_stf)
    counts: Counter[str] = Counter()
    changed = 0
    matcher = SequenceMatcher(a=raw, b=corrected, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        affected = raw[i1:i2] + corrected[j1:j2]
        changed += max(i2 - i1, j2 - j1)
        for category in {_category(token) for token in affected}:
            counts[category] += 1
    return {
        "raw_token_count": len(raw),
        "corrected_token_count": len(corrected),
        "changed_token_count": changed,
        "exact_token_match": raw == corrected,
        "categories": dict(sorted(counts.items())),
    }


def evaluation_metrics(
    expected_stf: dict[str, Any],
    candidate_stf: dict[str, Any],
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: int | None = None,
) -> dict[str, Any]:
    summary = correction_summary(candidate_stf, expected_stf)
    expected_lines = expected_stf.get("lines", [])
    candidate_lines = candidate_stf.get("lines", [])
    matching_lines = sum(
        left == right for left, right in zip(expected_lines, candidate_lines, strict=False)
    )
    line_total = max(len(expected_lines), len(candidate_lines))
    total = summary["corrected_token_count"]
    changed = summary["changed_token_count"]
    return {
        **summary,
        "exact_token_accuracy": 1.0 if total == 0 else max(0.0, (total - changed) / total),
        "matching_lines": matching_lines,
        "line_count": line_total,
        "line_accuracy": 1.0 if line_total == 0 else matching_lines / line_total,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
    }


def encode_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, sort_keys=True, separators=(",", ":"))
