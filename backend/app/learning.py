"""Phase 3.5 correction metrics and private-baseline evaluation helpers."""

import json
import re
from collections import Counter
from collections.abc import Iterable
from difflib import SequenceMatcher
from statistics import mean
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
    # A capital letter outside S R G M P D N is not sargam at all — it is the
    # misread `validate_stf` flags loudly (the live eval that read notes as "B").
    # It tokenizes as loose characters, so without this it would vanish into
    # `layout` and never surface as the worst symbol class.
    if len(symbol) == 1 and symbol.isascii() and symbol.isupper():
        return "alien_letter"
    # Orphaned marks left behind when a note token splits (e.g. `R_` -> `B` `_`).
    if symbol in {"_", "^"}:
        return "accidental"
    if symbol in {"'", ","}:
        return "octave"
    return "layout"


def _note_aspects(token: str) -> tuple[str, str, str]:
    """Split a note token into (letter, accidental marks, octave marks)."""
    mods = token[1:]
    return (
        token[0],
        "".join(sorted(ch for ch in mods if ch in "_^")),
        "".join(sorted(ch for ch in mods if ch in "',")),
    )


def _attribute_replacement(raw_token: str, corrected_token: str, counts: Counter[str]) -> None:
    """Charge a substitution to the aspect that actually differs.

    Two note tokens differing only in an accidental are an accidental error, not
    also a letter error — attributing to both categories inflates `letter` on
    every accidental fix and hides which mark the model really struggles with.
    """
    if NOTE_RE.fullmatch(raw_token) and NOTE_RE.fullmatch(corrected_token):
        raw_letter, raw_acc, raw_oct = _note_aspects(raw_token)
        new_letter, new_acc, new_oct = _note_aspects(corrected_token)
        if raw_letter != new_letter:
            counts["letter"] += 1
        if raw_acc != new_acc:
            counts["accidental"] += 1
        if raw_oct != new_oct:
            counts["octave"] += 1
        return
    counts[_category(raw_token)] += 1
    if _category(corrected_token) != _category(raw_token):
        counts[_category(corrected_token)] += 1


def correction_summary(raw_stf: dict[str, Any], corrected_stf: dict[str, Any]) -> dict[str, Any]:
    """Return privacy-preserving counts; never include the STF or token text.

    `categories` counts affected TOKENS (not edit blocks), so a sheet with forty
    wrong letters outranks one with a single wrong barline.
    """
    raw = _stf_tokens(raw_stf)
    corrected = _stf_tokens(corrected_stf)
    counts: Counter[str] = Counter()
    changed = 0
    matcher = SequenceMatcher(a=raw, b=corrected, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed += max(i2 - i1, j2 - j1)
        before, after = raw[i1:i2], corrected[j1:j2]
        for raw_token, corrected_token in zip(before, after, strict=False):
            _attribute_replacement(raw_token, corrected_token, counts)
        # Length mismatch: the tail is a pure deletion or insertion.
        for token in before[len(after) :] + after[len(before) :]:
            counts[_category(token)] += 1
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


BASELINE_SHEET_TARGET = 5


def _mean(values: Iterable[float]) -> float | None:
    collected = list(values)
    return mean(collected) if collected else None


def baseline_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-sheet metrics into the recognition baseline report.

    Shared by the CLI and the API so a locally-run report and a deployed one can
    never disagree. Aggregates only — never STF text, token text, or images.
    """
    category_totals: Counter[str] = Counter()
    for item in results:
        category_totals.update(item["categories"])
    total_corrections = sum(category_totals.values())
    corrected_tokens = sum(item["corrected_token_count"] for item in results)
    return {
        "reviewed_sheet_count": len(results),
        "baseline_ready": len(results) >= BASELINE_SHEET_TARGET,
        "sheets_needed": max(0, BASELINE_SHEET_TARGET - len(results)),
        "exact_sheet_matches": sum(item["exact_token_match"] for item in results),
        "mean_token_accuracy": _mean(item["exact_token_accuracy"] for item in results),
        "mean_line_accuracy": _mean(item["line_accuracy"] for item in results),
        # Worst symbol class first — this is what a targeted prompt fix aims at.
        "corrections_by_symbol": [
            {
                "category": category,
                "corrected_tokens": count,
                "share_of_all_corrections": round(count / total_corrections, 4),
                "per_1000_tokens": round(1000 * count / corrected_tokens, 2)
                if corrected_tokens
                else None,
                "sheets_affected": sum(1 for item in results if item["categories"].get(category)),
            }
            for category, count in category_totals.most_common()
        ],
        # Per sheet too, so one bad scan cannot hide behind the mean.
        "per_sheet": [
            {
                "sheet": index,
                "token_accuracy": round(item["exact_token_accuracy"], 4),
                "line_accuracy": round(item["line_accuracy"], 4),
                "changed_tokens": item["changed_token_count"],
                "categories": item["categories"],
            }
            for index, item in enumerate(results, start=1)
        ],
        "total_input_tokens": sum(item["input_tokens"] or 0 for item in results),
        "total_output_tokens": sum(item["output_tokens"] or 0 for item in results),
        "mean_latency_ms": _mean(
            item["latency_ms"] for item in results if item["latency_ms"] is not None
        ),
    }


def encode_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, sort_keys=True, separators=(",", ":"))
