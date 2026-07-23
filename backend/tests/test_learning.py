from app.learning import correction_summary, evaluation_metrics


def _stf(text: str) -> dict:
    return {
        "header": {"concert_scale": "G", "alto_scale": "E", "beat": "4/4"},
        "lines": [{"n": 1, "kind": "sargam", "text": text}],
    }


def test_correction_summary_classifies_marks_without_leaking_tokens():
    summary = correction_summary(_stf("S R G | P"), _stf("S R_ G' | P -"))
    assert summary["exact_token_match"] is False
    assert summary["categories"]["accidental"] >= 1
    assert summary["categories"]["octave"] >= 1
    assert summary["categories"]["rhythm"] >= 1
    assert "S R" not in str(summary)


def test_evaluation_metrics_include_accuracy_cost_and_latency():
    metrics = evaluation_metrics(
        _stf("S R G"),
        _stf("S R G"),
        input_tokens=100,
        output_tokens=20,
        latency_ms=1500,
    )
    assert metrics["exact_token_accuracy"] == 1
    assert metrics["line_accuracy"] == 1
    assert metrics["input_tokens"] == 100
    assert metrics["output_tokens"] == 20
    assert metrics["latency_ms"] == 1500
