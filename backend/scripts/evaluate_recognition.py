"""Report the current private reviewed-sheet recognition baseline.

Run from backend/: uv run python -m scripts.evaluate_recognition
The report contains aggregate metrics only; it never prints images or STF.

Phase 3.5 tiling A/B: `--compare` runs the whole-page control and the `--tiled
half` recognizer in ONE batch over the same reviewed sheets and prints the delta
(combined accidental+octave per 1k tokens, the ladder gate, and a guardrail check
that no non-diacritic category regresses). `--control-runs N` repeats the control
to expose the model's run-to-run noise band, so a tiled win can be told apart from
sampling noise (the whole reason the stored single-sample baseline is reference
only). See the vault note `saregamapic/phase-3-5-tiling-experiment`.

Model A/B: `--compare-model CANDIDATE` replays the configured model (control) and
CANDIDATE over the same reviewed sheets, `--control-runs N` times EACH, with
`--effort` pinned on both arms (model defaults differ, e.g. Opus 5.5 = medium), and
prints `compare_model_reports`: every metric's per-run values for both arms and a
verdict that only counts a difference when the two arms' run ranges don't overlap.
Each arm's report is also echoed to stderr as it finishes, so a failure late in a
long run doesn't lose the arms already paid for.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Any

from app.learning import baseline_report, evaluation_metrics
from app.recognition import Recognizer, make_recognizer, make_tiled_recognizer, read_scan_bytes

# The diacritics tiling targets, and the categories that must not regress in
# exchange for a diacritic win (the design's hard guardrail).
DIACRITIC_CATEGORIES = ("accidental", "octave")
NON_DIACRITIC_GUARDRAIL = ("letter", "layout", "curve", "rhythm", "barline")
LADDER_GATE = 0.20  # ~20% relative reduction in combined accidental+octave / 1k


def fetch_rows(db: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn.execute(
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


def replay_results(
    recognizer: Recognizer, rows: list[sqlite3.Row], data_dir: Path
) -> list[dict[str, Any]]:
    """Run `recognizer` fresh on each scan, diffing against the corrected STF."""
    results = []
    for row in rows:
        started = time.monotonic()
        candidate = recognizer(
            read_scan_bytes(data_dir, row["image_path"]), row["content_type"]
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
    return results


def stored_results(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Metrics from the STORED raw recognition (no API call)."""
    return [
        evaluation_metrics(
            json.loads(row["corrected_stf_json"]),
            json.loads(row["raw_stf_json"]),
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            latency_ms=row["latency_ms"],
        )
        for row in rows
    ]


def _per1k_by_category(report: dict[str, Any]) -> dict[str, float]:
    return {
        c["category"]: (c["per_1000_tokens"] or 0.0)
        for c in report["corrections_by_symbol"]
    }


def _combined_diacritic_per1k(report: dict[str, Any]) -> float:
    by_cat = _per1k_by_category(report)
    return round(sum(by_cat.get(c, 0.0) for c in DIACRITIC_CATEGORIES), 2)


def _total_per1k(report: dict[str, Any]) -> float:
    return round(sum((c["per_1000_tokens"] or 0.0) for c in report["corrections_by_symbol"]), 2)


def compare_reports(
    control_reports: list[dict[str, Any]],
    tiled_report: dict[str, Any],
    *,
    gate: float = LADDER_GATE,
) -> dict[str, Any]:
    """Tiled-vs-control verdict. Pure: only reads two report dicts.

    `per_1000_tokens` denominators are the ground-truth token count (identical for
    both recognizers on the same reviewed corpus), so control and tiled rates are
    directly comparable. When more than one control run is supplied, their spread
    is the noise band a tiled win must clear.
    """
    control_combined = [_combined_diacritic_per1k(r) for r in control_reports]
    control_total = [_total_per1k(r) for r in control_reports]
    control_tok = [r["mean_token_accuracy"] for r in control_reports]

    c_combined_mean = round(mean(control_combined), 2)
    t_combined = _combined_diacritic_per1k(tiled_report)
    rel = (
        None
        if c_combined_mean == 0
        else round((c_combined_mean - t_combined) / c_combined_mean, 4)
    )

    categories: set[str] = set()
    for report in (*control_reports, tiled_report):
        categories |= set(_per1k_by_category(report))
    tiled_cat = _per1k_by_category(tiled_report)
    per_category = []
    for cat in categories:
        control_vals = [_per1k_by_category(r).get(cat, 0.0) for r in control_reports]
        control_cat_mean = round(mean(control_vals), 2)
        tiled_val = round(tiled_cat.get(cat, 0.0), 2)
        per_category.append(
            {
                "category": cat,
                "control_per_1k": control_cat_mean,
                "tiled_per_1k": tiled_val,
                "delta_per_1k": round(tiled_val - control_cat_mean, 2),
            }
        )
    per_category.sort(key=lambda d: d["control_per_1k"], reverse=True)
    regressions = [
        d["category"]
        for d in per_category
        if d["category"] in NON_DIACRITIC_GUARDRAIL and d["delta_per_1k"] > 0
    ]

    c_total_mean = round(mean(control_total), 2)
    t_total = _total_per1k(tiled_report)
    t_tok = tiled_report["mean_token_accuracy"]
    control_tok_ok = all(x is not None for x in control_tok)
    c_tok_mean = round(mean(control_tok), 4) if control_tok_ok else None
    have_tok = control_tok_ok and t_tok is not None

    return {
        "reviewed_sheet_count": tiled_report["reviewed_sheet_count"],
        "control_runs": len(control_reports),
        "primary": {
            "combined_accidental_octave_per_1k": {
                "control_mean": c_combined_mean,
                "control_runs": control_combined,
                "tiled": t_combined,
                "abs_reduction": round(c_combined_mean - t_combined, 2),
                "relative_reduction": rel,
            },
            "total_corrections_per_1k": {
                "control_mean": c_total_mean,
                "control_runs": control_total,
                "tiled": t_total,
                "abs_reduction": round(c_total_mean - t_total, 2),
            },
            "mean_token_accuracy": {
                "control_mean": c_tok_mean,
                "tiled": round(t_tok, 4) if t_tok is not None else None,
                "delta": round(t_tok - c_tok_mean, 4) if have_tok else None,
            },
        },
        "ladder_gate": {
            "threshold_relative_reduction": gate,
            "achieved_relative_reduction": rel,
            "pass": bool(rel is not None and rel >= gate),
        },
        "guardrail": {
            "net_total_corrections_down": t_total < c_total_mean,
            "non_diacritic_regressions": regressions,
            # Only meaningful with a noise band (>1 control run): does tiled beat
            # the best control run, i.e. clear run-to-run stochasticity?
            "beyond_control_noise": bool(
                len(control_combined) > 1 and t_combined < min(control_combined)
            ),
            "per_category_per_1k": per_category,
        },
    }


def _arm_metrics(report: dict[str, Any]) -> dict[str, float | None]:
    """The headline numbers compared between model arms, for one run's report."""
    sheets = report["reviewed_sheet_count"] or 1
    return {
        "combined_accidental_octave_per_1k": _combined_diacritic_per1k(report),
        "total_corrections_per_1k": _total_per1k(report),
        "mean_token_accuracy": report["mean_token_accuracy"],
        "mean_line_accuracy": report["mean_line_accuracy"],
        "input_tokens_per_sheet": round(report["total_input_tokens"] / sheets),
        "output_tokens_per_sheet": round(report["total_output_tokens"] / sheets),
        "mean_latency_ms": report["mean_latency_ms"],
    }


# For these, LOWER is better; for the accuracies, higher is better. Cost and
# latency are reported but never decide the verdict.
_LOWER_IS_BETTER = ("combined_accidental_octave_per_1k", "total_corrections_per_1k")
_HIGHER_IS_BETTER = ("mean_token_accuracy", "mean_line_accuracy")


def _verdict(control: list[float], candidate: list[float], *, lower_is_better: bool) -> str:
    """'better' / 'worse' only when the arms' run ranges don't overlap at all."""
    if lower_is_better:
        if max(candidate) < min(control):
            return "better"
        if min(candidate) > max(control):
            return "worse"
    else:
        if min(candidate) > max(control):
            return "better"
        if max(candidate) < min(control):
            return "worse"
    return "inside_noise"


def compare_model_reports(
    control_reports: list[dict[str, Any]], candidate_reports: list[dict[str, Any]]
) -> dict[str, Any]:
    """Model-vs-model verdict. Pure: only reads the per-run report dicts.

    Both arms run over the same reviewed corpus, so per-1k rates share a
    denominator and are directly comparable. With one run per arm there is no
    noise band, and every verdict collapses to a single-sample comparison — the
    A/B should therefore run with `--control-runs 2` or more.
    """
    control = [_arm_metrics(r) for r in control_reports]
    candidate = [_arm_metrics(r) for r in candidate_reports]

    metrics: dict[str, Any] = {}
    for name in control[0]:
        c_vals = [m[name] for m in control if m[name] is not None]
        k_vals = [m[name] for m in candidate if m[name] is not None]
        entry: dict[str, Any] = {
            "control_runs": c_vals,
            "candidate_runs": k_vals,
            "control_mean": round(mean(c_vals), 4) if c_vals else None,
            "candidate_mean": round(mean(k_vals), 4) if k_vals else None,
        }
        if c_vals and k_vals:
            entry["delta"] = round(entry["candidate_mean"] - entry["control_mean"], 4)
            if name in _LOWER_IS_BETTER or name in _HIGHER_IS_BETTER:
                entry["verdict"] = _verdict(
                    c_vals, k_vals, lower_is_better=name in _LOWER_IS_BETTER
                )
        metrics[name] = entry

    categories: set[str] = set()
    for report in (*control_reports, *candidate_reports):
        categories |= set(_per1k_by_category(report))
    per_category = []
    for cat in categories:
        c_mean = round(mean(_per1k_by_category(r).get(cat, 0.0) for r in control_reports), 2)
        k_mean = round(mean(_per1k_by_category(r).get(cat, 0.0) for r in candidate_reports), 2)
        per_category.append(
            {
                "category": cat,
                "control_per_1k": c_mean,
                "candidate_per_1k": k_mean,
                "delta_per_1k": round(k_mean - c_mean, 2),
            }
        )
    per_category.sort(key=lambda d: d["control_per_1k"], reverse=True)

    total = metrics["total_corrections_per_1k"]
    c_total, k_total = total["control_mean"], total["candidate_mean"]
    return {
        "reviewed_sheet_count": control_reports[0]["reviewed_sheet_count"],
        "runs_per_arm": [len(control_reports), len(candidate_reports)],
        "relative_reduction_total_corrections": (
            None
            if not c_total
            else round((c_total - k_total) / c_total, 4)
        ),
        "metrics": metrics,
        "per_category_per_1k": per_category,
    }


def _replay_arm(label: str, recognizer: Recognizer, rows, data_dir: Path) -> dict[str, Any]:
    report = baseline_report(replay_results(recognizer, rows, data_dir))
    line = json.dumps({"arm": label, "report": report}, sort_keys=True)
    print(line, file=sys.stderr, flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("../data/saregamapic.db"))
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Run the configured model on each reviewed scan (incurs API cost)",
    )
    parser.add_argument(
        "--tiled",
        choices=["half"],
        default=None,
        help=(
            "Phase 3.5 tiling variant to replay instead of the whole-page control: "
            "'half' = Rung 1 (two overlapping half-page bands). Omit for the "
            "whole-page control. Requires --replay. NOTE: Rung 1 was A/B'd and "
            "refuted (2026-07-26) — kept for reproducibility, not adoption."
        ),
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help=(
            "Phase 3.5 A/B: replay the whole-page control AND --tiled half in one "
            "batch over the same sheets and print the delta + ladder gate + "
            "guardrail. Requires --model; incurs API cost."
        ),
    )
    parser.add_argument(
        "--control-runs",
        type=int,
        default=1,
        help="With --compare: repeat the control this many times for a noise band (default 1).",
    )
    parser.add_argument("--model", default=os.getenv("SAREGAMAPIC_MODEL", ""))
    parser.add_argument(
        "--compare-model",
        metavar="CANDIDATE",
        default="",
        help=(
            "Model A/B: replay --model (control) and CANDIDATE whole-page over the same "
            "sheets, --control-runs times each, and print compare_model_reports. "
            "Incurs API cost."
        ),
    )
    parser.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        default="high",
        help="With --compare-model: effort pinned on BOTH arms (default high, Opus 4.8's).",
    )
    args = parser.parse_args()

    if args.compare and args.compare_model:
        parser.error("--compare (tiling) and --compare-model are separate experiments")
    if args.compare_model and (args.tiled or args.replay):
        parser.error("--compare-model replays both arms itself; drop --tiled/--replay")
    if args.compare and args.tiled:
        parser.error("--compare runs both control and tiled; do not also pass --tiled")
    if args.tiled and not args.replay:
        parser.error("--tiled requires --replay")
    if args.control_runs < 1:
        parser.error("--control-runs must be >= 1")

    rows = fetch_rows(args.db)

    if args.compare_model:
        if not args.model:
            parser.error("--model or SAREGAMAPIC_MODEL is required with --compare-model")
        if not rows:
            parser.error(
                "no reviewed sheets with a succeeded recognition run in this DB "
                f"({args.db}) — nothing to compare"
            )
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        control = make_recognizer(api_key, args.model, effort=args.effort)
        candidate = make_recognizer(api_key, args.compare_model, effort=args.effort)
        # Interleave the arms so drift over the run (API load, time of day) hits
        # both equally rather than all control first, all candidate last.
        control_reports, candidate_reports = [], []
        for run in range(1, args.control_runs + 1):
            control_reports.append(
                _replay_arm(f"control {args.model} run {run}", control, rows, args.data_dir)
            )
            candidate_reports.append(
                _replay_arm(
                    f"candidate {args.compare_model} run {run}", candidate, rows, args.data_dir
                )
            )
        print(
            json.dumps(
                {
                    "control_model": args.model,
                    "candidate_model": args.compare_model,
                    "effort": args.effort,
                    "comparison": compare_model_reports(control_reports, candidate_reports),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.compare:
        if not args.model:
            parser.error("--model or SAREGAMAPIC_MODEL is required with --compare")
        if not rows:
            parser.error(
                "no reviewed sheets with a succeeded recognition run in this DB "
                f"({args.db}) — nothing to compare"
            )
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        control = make_recognizer(api_key, args.model)
        tiled = make_tiled_recognizer(api_key, args.model, tiles=2)
        control_reports = [
            baseline_report(replay_results(control, rows, args.data_dir))
            for _ in range(args.control_runs)
        ]
        tiled_report = baseline_report(replay_results(tiled, rows, args.data_dir))
        print(
            json.dumps(
                {
                    "comparison": compare_reports(control_reports, tiled_report),
                    "control_reports": control_reports,
                    "tiled_report": tiled_report,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.replay:
        if not args.model:
            parser.error("--model or SAREGAMAPIC_MODEL is required with --replay")
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        recognizer = (
            make_tiled_recognizer(api_key, args.model, tiles=2)
            if args.tiled == "half"
            else make_recognizer(api_key, args.model)
        )
        results = replay_results(recognizer, rows, args.data_dir)
    else:
        results = stored_results(rows)

    print(json.dumps(baseline_report(results), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
