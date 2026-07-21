"""STF validation unit tests (standard v1.1 rules)."""

from app.stf import parse_pitch_class, validate_stf


def _sargam(text: str) -> dict:
    return {"header": {}, "lines": [{"n": 1, "kind": "sargam", "text": text}]}


def test_clean_line_has_no_warnings():
    assert validate_stf(_sargam("S R - G_ | (SRGM) P | N, S' M^ R_ |")) == []


def test_illegal_accidentals_flagged():
    assert any("S and P never" in w for w in validate_stf(_sargam("S_ R")))
    assert any("only M may be sharp" in w for w in validate_stf(_sargam("R^ G")))
    assert any("only R G D N may be flat" in w for w in validate_stf(_sargam("M_ P")))


def test_alien_letter_flagged_as_misread():
    # 'B' isn't a sargam letter — the first live eval produced these misreads.
    warns = validate_stf(_sargam("R B_ G"))
    assert any("'B' is not a sargam note" in w for w in warns)
    # valid note letters never trigger the alien check
    assert validate_stf(_sargam("S R G M P D N")) == []


def test_curve_group_must_span_two_slots():
    # A single bare note in parens is a phantom curve (or a misread accidental).
    assert any("fewer than 2 slots" in w for w in validate_stf(_sargam("(S) R")))
    assert validate_stf(_sargam("(GM) R")) == []
    # A leading hold/rest slot delays a lone note to the half-beat — a legal curve
    # that must be preserved, not collapsed to a bare note.
    assert validate_stf(_sargam("(-G) R")) == []
    assert validate_stf(_sargam("(+G) R")) == []


def test_header_nine_semitone_cross_check():
    ok = {"header": {"concert_scale": "G", "alto_scale": "E"}, "lines": []}
    assert validate_stf(ok) == []
    bad = {"header": {"concert_scale": "G", "alto_scale": "F"}, "lines": []}
    assert any("concert + 9 semitones" in w for w in validate_stf(bad))


def test_parse_pitch_class_handles_accidentals_and_quality():
    assert parse_pitch_class("C") == 0
    assert parse_pitch_class("D maj") == 2
    assert parse_pitch_class("Eb") == 3
    assert parse_pitch_class("B♭") == 10  # B flat
    assert parse_pitch_class("F#") == 6
    assert parse_pitch_class("") is None


def test_lyric_and_section_lines_are_not_note_validated():
    doc = {
        "header": {},
        "lines": [
            {"n": 1, "kind": "lyric", "text": "S_ P is fine here — free text"},
            {"n": 2, "kind": "section", "text": "Chorus *4"},
        ],
    }
    assert validate_stf(doc) == []
