"""Report the current private reviewed-sheet recognition baseline.

Run from backend/: uv run python -m scripts.evaluate_recognition
The report contains aggregate metrics only; it never prints images or STF.
"""

import argparse
import json
import os
import sqlite3
import time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from statistics import mean

from app.learning import evaluation_metrics
from app.recognition import make_recognizer, read_scan_bytes


def _mean(values: Iterable[float]) -> float | None:
    collected = list(values)
    return mean(collected) if collected else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("../data/saregamapic.db"))
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Run the configured model on each reviewed scan (incurs API cost)",
    )
    parser.add_argument("--model", default=os.getenv("SAREGAMAPIC_MODEL", ""))
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT rr.raw_stf_json, rr.input_tokens, rr.output_tokens, rr.latency_ms,
               tr.stf_json AS corrected_stf_json, sc.image_path, sc.content_type
        FROM transcriptions tr
        JOIN recognition_runs rr ON rr.id = tr.recognition_run_id
        JOIN scans sc ON sc.id = tr.scan_id
        WHERE tr.status = 'reviewed' AND rr.outcome = 'succeeded'
        ORDER BY rr.created_at
        """
    ).fetchall()
    if args.replay:
        if not args.model:
            parser.error("--model or SAREGAMAPIC_MODEL is required with --replay")
        recognizer = make_recognizer(os.getenv("ANTHROPIC_API_KEY", ""), args.model)
        results = []
        for row in rows:
            started = time.monotonic()
            candidate = recognizer(
                read_scan_bytes(args.data_dir, row["image_path"]), row["content_type"]
            )
            results.append(
                evaluation_metrics(
                    json.loads(row["corrected_stf_json"]),
                    candidate.stf,
                    input_tokens=candidate.input_tokens,
                    output_tokens=candidate.output_tokens,
                    latency_ms=round((time.monotonic() - started) * 1000),
                )
            )
    else:
        results = [
            evaluation_metrics(
                json.loads(row["corrected_stf_json"]),
                json.loads(row["raw_stf_json"]),
                input_tokens=row["input_tokens"],
                output_tokens=row["output_tokens"],
                latency_ms=row["latency_ms"],
            )
            for row in rows
        ]
    # Which symbol classes actually cost the most corrections, worst first —
    # this is what a targeted prompt fix is aimed at.
    category_totals: Counter[str] = Counter()
    for item in results:
        category_totals.update(item["categories"])
    corrected_tokens = sum(item["corrected_token_count"] for item in results)

    report = {
        "reviewed_sheet_count": len(results),
        "baseline_ready": len(results) >= 5,
        "exact_sheet_matches": sum(item["exact_token_match"] for item in results),
        "mean_token_accuracy": _mean(item["exact_token_accuracy"] for item in results),
        "mean_line_accuracy": _mean(item["line_accuracy"] for item in results),
        "corrections_by_symbol": [
            {
                "category": category,
                "corrected_tokens": count,
                "share_of_all_corrections": round(count / sum(category_totals.values()), 4),
                "per_1000_tokens": round(1000 * count / corrected_tokens, 2)
                if corrected_tokens
                else None,
                "sheets_affected": sum(1 for item in results if item["categories"].get(category)),
            }
            for category, count in category_totals.most_common()
        ],
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
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
