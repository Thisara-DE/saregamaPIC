"""Recognition-learning reporting (Phase 3.5).

The evaluation CLI reads a SQLite file directly, which works locally but not
against a deployed Railway volume (the image ships `app/`, not `scripts/`).
This exposes the same shared report over the API so the baseline can be read
from whichever environment the sheets actually live in.

Aggregates only — the response never contains STF, token text, or image data.
"""

import json
import sqlite3

from fastapi import APIRouter, Request

from ..auth import current_user_id
from ..learning import baseline_report, evaluation_metrics
from ..schemas import RecognitionBaseline

router = APIRouter()

# A sheet counts only when its raw model draft was preserved (migration 005) and
# a human reviewed it. Scoped to the caller: one user's baseline never mixes
# with another's, matching per-user ownership isolation.
_PAIRS = """
    SELECT rr.raw_stf_json, rr.input_tokens, rr.output_tokens, rr.latency_ms,
           tr.stf_json AS corrected_stf_json
    FROM transcriptions tr
    JOIN recognition_runs rr ON rr.id = tr.recognition_run_id
    JOIN scans sc ON sc.id = tr.scan_id
    JOIN songs so ON so.id = sc.song_id
    WHERE tr.status = 'reviewed' AND rr.outcome = 'succeeded' AND so.owner_id = ?
    ORDER BY rr.created_at
"""


@router.get("/recognition/baseline", response_model=RecognitionBaseline)
def recognition_baseline(request: Request) -> RecognitionBaseline:
    """Report how well recognition does on this user's reviewed sheets."""
    conn: sqlite3.Connection = request.state.db
    rows = conn.execute(_PAIRS, (current_user_id(request),)).fetchall()
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
    return RecognitionBaseline(**baseline_report(results))
