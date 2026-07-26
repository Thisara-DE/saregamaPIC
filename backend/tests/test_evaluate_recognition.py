"""Unit tests for the Phase 3.5 tiling A/B comparison logic.

Only the pure `compare_reports` verdict is tested here — the replay path makes
real API calls and is exercised manually against the environment's data volume.
"""

from app.learning import baseline_report
from scripts.evaluate_recognition import compare_reports


def _result(categories: dict[str, int], *, corrected_tokens: int = 1000, token_acc: float = 0.7):
    """One synthetic per-sheet metrics dict shaped like `evaluation_metrics`.

    With `corrected_tokens=1000`, each category's `per_1000_tokens` equals its raw
    count, which keeps the arithmetic in the assertions obvious.
    """
    changed = sum(categories.values())
    return {
        "categories": dict(categories),
        "corrected_token_count": corrected_tokens,
        "changed_token_count": changed,
        "exact_token_match": changed == 0,
        "exact_token_accuracy": token_acc,
        "line_accuracy": 0.3,
        "input_tokens": 100,
        "output_tokens": 100,
        "latency_ms": 1000,
    }


def _report(categories: dict[str, int], *, token_acc: float = 0.7):
    return baseline_report([_result(categories, token_acc=token_acc)])


def test_tiling_clears_gate_and_guardrail():
    control = _report({"accidental": 100, "octave": 60, "letter": 50}, token_acc=0.71)
    tiled = _report({"accidental": 70, "octave": 40, "letter": 50}, token_acc=0.78)

    verdict = compare_reports([control], tiled)

    combined = verdict["primary"]["combined_accidental_octave_per_1k"]
    assert combined["control_mean"] == 160.0
    assert combined["tiled"] == 110.0
    # (160 - 110) / 160 = 0.3125
    assert combined["relative_reduction"] == 0.3125
    assert verdict["ladder_gate"]["pass"] is True
    assert verdict["guardrail"]["net_total_corrections_down"] is True
    assert verdict["guardrail"]["non_diacritic_regressions"] == []
    assert verdict["primary"]["mean_token_accuracy"]["delta"] == 0.07


def test_non_diacritic_regression_is_flagged():
    control = _report({"accidental": 100, "octave": 60, "curve": 20})
    # Diacritics improve but stitching doubles the curve errors.
    tiled = _report({"accidental": 70, "octave": 40, "curve": 45})

    verdict = compare_reports([control], tiled)

    assert verdict["ladder_gate"]["pass"] is True  # diacritics still cleared
    assert "curve" in verdict["guardrail"]["non_diacritic_regressions"]


def test_gate_fails_on_small_reduction():
    control = _report({"accidental": 100, "octave": 60})
    tiled = _report({"accidental": 95, "octave": 55})  # 160 -> 150 = 6.25%

    verdict = compare_reports([control], tiled)

    assert verdict["ladder_gate"]["achieved_relative_reduction"] == 0.0625
    assert verdict["ladder_gate"]["pass"] is False


def test_noise_band_from_multiple_control_runs():
    controls = [
        _report({"accidental": 100, "octave": 60}),  # 160
        _report({"accidental": 90, "octave": 70}),  # 160
        _report({"accidental": 110, "octave": 58}),  # 168
    ]
    tiled = _report({"accidental": 70, "octave": 40})  # 110, below every control run

    verdict = compare_reports(controls, tiled)

    assert verdict["control_runs"] == 3
    combined = verdict["primary"]["combined_accidental_octave_per_1k"]
    assert combined["control_runs"] == [160.0, 160.0, 168.0]
    assert verdict["guardrail"]["beyond_control_noise"] is True


def test_tiled_inside_noise_band_does_not_clear_it():
    controls = [
        _report({"accidental": 100, "octave": 60}),  # 160
        _report({"accidental": 70, "octave": 45}),  # 115  (a lucky control run)
    ]
    tiled = _report({"accidental": 80, "octave": 40})  # 120, not below min control (115)

    verdict = compare_reports(controls, tiled)

    assert verdict["guardrail"]["beyond_control_noise"] is False
