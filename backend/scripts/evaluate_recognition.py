"""Report the current private reviewed-sheet recognition baseline.

Run from backend/: uv run python -m scripts.evaluate_recognition
The report contains aggregate metrics only; it never prints images or STF.
"""

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from statistics import mean

from app.learning import evaluation_metrics
from app.recognition import make_recognizer, read_scan_bytes


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
    report = {
        "reviewed_sheet_count": len(results),
        "baseline_ready": len(results) >= 5,
        "exact_sheet_matches": sum(item["exact_token_match"] for item in results),
        "mean_token_accuracy": mean(item["exact_token_accuracy"] for item in results)
        if results
        else None,
        "mean_line_accuracy": mean(item["line_accuracy"] for item in results)
        if results
        else None,
        "total_input_tokens": sum(item["input_tokens"] or 0 for item in results),
        "total_output_tokens": sum(item["output_tokens"] or 0 for item in results),
        "mean_latency_ms": mean(item["latency_ms"] for item in results) if results else None,
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
