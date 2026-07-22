"""Sargam Text Format (STF) — the canonical transcription store + validation.

STF is the ASCII, diff-able, prompt-able encoding of a hand-written sheet,
governed by the project's notation standard v1.1.
A transcription's ``stf_json`` is ``{"header": {...}, "lines": [...]}``:

    header: {concert_scale, alto_scale, beat}   (empty strings when absent)
    lines:  [{n, kind, text}, ...]              (verbatim, layout preserved)

Token encoding (paper ↔ ASCII), marks combine e.g. lower-octave flat Re = ``R_,``:

    R      natural            R_   flat (underline)      M^   sharp (M only, overline)
    S'     upper octave dot   S,   lower octave dot
    -      hold prev beat     +    one-beat rest         |    barline      //  repeat
    (SRGM) curve: group shares one beat                  [ … ]  other instrument / decoration

Validation is ADVISORY: it returns warnings, never mutates or rejects. The
reviewer is the authority (fidelity + human-in-the-loop rules) — the UI surfaces
warnings prominently, especially the dot-vs-dash confusions, but the user decides.
"""

import re

# Semitones from S for each natural letter (the fixed-S chromatic space).
NATURAL_PC = {"S": 0, "R": 2, "G": 4, "M": 5, "P": 7, "D": 9, "N": 11}
# Only these letters may take a flat (dash underneath). M takes a sharp; S/P take neither.
FLAT_ALLOWED = {"R", "G", "D", "N"}

# Western note name -> pitch class (0..11), for the header 9-semitone cross-check.
_NOTE_BASE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# A sargam note token: a letter, then any mix of octave dots and one accidental.
_NOTE_RE = re.compile(r"[SRGMPDN][_^',]*")
# Any OTHER capital letter in a note line is not sargam — almost always a
# recognition misread (e.g. B for R). Flag it loudly.
_ALIEN_LETTER_RE = re.compile(r"[A-Z]")


def parse_pitch_class(scale: str) -> int | None:
    """Western scale name -> pitch class (0..11). Ignores quality words (maj/minor).

    Accepts ``G``, ``Eb``, ``B♭``, ``F#``, ``D maj``, ``C minor`` etc. Returns None
    when the leading token isn't a recognizable note letter.
    """
    s = scale.strip()
    if not s or s[0].upper() not in _NOTE_BASE:
        return None
    pc = _NOTE_BASE[s[0].upper()]
    for ch in s[1:]:
        if ch in ("#", "♯"):  # sharp
            pc += 1
        elif ch in ("b", "♭"):  # flat
            pc -= 1
        else:
            break  # stop at the first non-accidental (space, quality word, …)
    return pc % 12


def _note_warnings(letter: str, mods: str, line_no: int, token: str) -> list[str]:
    """Illegal-accidental checks for one note token (standard v1.1)."""
    warnings: list[str] = []
    has_flat = "_" in mods
    has_sharp = "^" in mods
    if has_flat and has_sharp:
        warnings.append(f"line {line_no}: '{token}' has both a flat and a sharp mark")
    if letter in ("S", "P") and (has_flat or has_sharp):
        warnings.append(f"line {line_no}: '{token}' — S and P never take an accidental")
    if has_flat and letter not in FLAT_ALLOWED:
        warnings.append(f"line {line_no}: '{token}' — only R G D N may be flat (not {letter})")
    if has_sharp and letter != "M":
        warnings.append(f"line {line_no}: '{token}' — only M may be sharp (not {letter})")
    return warnings


def _line_warnings(line_no: int, text: str) -> list[str]:
    """Per-line checks: illegal accidentals, alien letters, curves spanning < 2 slots."""
    warnings: list[str] = []
    for m in _NOTE_RE.finditer(text):
        token = m.group()
        warnings.extend(_note_warnings(token[0], token[1:], line_no, token))
    # Any capital letter that isn't a sargam note (S R G M P D N) is a misread —
    # in the first live eval the model read some notes as "B" (not in the system).
    for alien in sorted(set(_ALIEN_LETTER_RE.findall(text)) - NATURAL_PC.keys()):
        warnings.append(f"line {line_no}: '{alien}' is not a sargam note — likely a misread")
    # Curve groups: each (...) must span at least two SLOTS — a slot is a note, a
    # `-` (hold) or a `+` (rest). A leading slot delays a lone note within the beat,
    # so `(-G)` / `(+G)` are legal (half-beat entries); only a single bare note is not.
    for group in re.findall(r"\(([^()]*)\)", text):
        slots = len(_NOTE_RE.findall(group)) + group.count("-") + group.count("+")
        if slots < 2:
            warnings.append(f"line {line_no}: a curve group '({group})' spans fewer than 2 slots")
    return warnings


# Line kinds that carry sargam note tokens (worth validating). Others (lyric,
# section, roadmap, annotation) are free text and pass through untouched.
_NOTE_KINDS = {"sargam", "run"}

# A sheet with at least this many barred `sargam` lines but zero curves is almost
# certainly a curve-dropping recognition run (faint slur arcs are the easiest mark
# to miss), so flag it. Below the floor a curveless sheet is plausible.
_MIN_SARGAM_LINES_FOR_CURVE_CHECK = 3


def validate_stf(stf: dict) -> list[str]:
    """Return advisory warnings for an STF document. Never raises on shape;
    unexpected fields are tolerated (a draft may be partial)."""
    warnings: list[str] = []

    header = stf.get("header") or {}
    concert = parse_pitch_class(header.get("concert_scale", "") or "")
    alto = parse_pitch_class(header.get("alto_scale", "") or "")
    if concert is not None and alto is not None and (concert + 9) % 12 != alto:
        warnings.append(
            "header: alto scale should be concert + 9 semitones "
            f"({header.get('concert_scale')} / {header.get('alto_scale')} are not)"
        )

    sargam_lines = 0
    curve_groups = 0
    for line in stf.get("lines") or []:
        if not isinstance(line, dict) or line.get("kind") not in _NOTE_KINDS:
            continue
        n = line.get("n")
        text = str(line.get("text", ""))
        if line.get("kind") == "sargam":
            sargam_lines += 1
        curve_groups += text.count("(")
        warnings.extend(_line_warnings(n if isinstance(n, int) else 0, text))

    # Curve-dropping run guard: faint slur arcs are the easiest mark to miss, and a
    # whole sheet coming back with none is the classic failure mode. Advisory only.
    if sargam_lines >= _MIN_SARGAM_LINES_FOR_CURVE_CHECK and curve_groups == 0:
        warnings.append(
            f"no curves found across {sargam_lines} sargam lines — verify the slur "
            "arcs weren't missed (faint pencil curves are the easiest mark to drop)"
        )

    return warnings
