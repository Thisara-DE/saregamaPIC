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


def test_accidental_fix_is_not_also_counted_as_a_letter_error():
    """`R_` -> `R` changes one mark. Charging it to `letter` too would make
    letters look like the worst category on any sheet full of flats."""
    summary = correction_summary(_stf("S R_ G | P"), _stf("S R G | P"))
    assert summary["categories"]["accidental"] == 1
    assert "letter" not in summary["categories"]


def test_octave_and_letter_errors_are_attributed_separately():
    summary = correction_summary(_stf("S R G"), _stf("S D G'"))
    assert summary["categories"]["letter"] == 1
    assert summary["categories"]["octave"] == 1


def test_categories_count_tokens_so_the_worst_symbol_class_ranks_first():
    """Ranking drives prompt fixes: four dropped curves must outrank one
    dropped barline, which per-edit-block counting could not express."""
    summary = correction_summary(_stf("(SR) (GM) (PD) (NS) | S"), _stf("SR GM PD NS S"))
    assert summary["categories"]["curve"] == 8
    assert summary["categories"]["barline"] == 1


def test_non_sargam_misread_is_reported_as_alien_not_buried_in_layout():
    """A note read as "B" is the misread `validate_stf` flags. It tokenizes as
    loose characters, so the catch-all used to hide the pipeline's loudest
    failure signal."""
    summary = correction_summary(_stf("S B G | P"), _stf("S R G | P"))
    assert summary["categories"]["alien_letter"] == 1
    assert "layout" not in summary["categories"]


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
