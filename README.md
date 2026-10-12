# SaReGaMaPic

*Point. Shoot. Sa Re Ga Ma.*

SaReGaMaPic turns photographs of handwritten sargam music sheets into faithful,
readable digital copies. It is a personal music library for Sinhala songs
transcribed by ear for Alto Saxophone and bamboo flutes.

The app keeps the handwritten page and its digital transcription together. A song
can contain several pages, and each page can be viewed as the original photograph or
as clean digital sargam notation. Western staff notation is the next major view
planned for the app.

## Why it exists

Handwritten transcriptions are valuable but fragile. They can be difficult to search,
awkward to read on a small screen, and easy to lose or damage. Retyping every page is
slow, especially when the notation contains octave dots, accidentals, curves, holds,
rests, repeats, lyrics, and handwritten performance notes.

SaReGaMaPic is designed to make those sheets easier to preserve and use without
changing what was written. The digital copy is a transcription of the page, not a
new arrangement or an attempt to “improve” the music.

## How it works

1. Photograph a handwritten sheet with a phone or tablet, or choose an existing
   image.
2. Optionally name the song. If left untitled, recognition can copy a clearly
   written title from the top of the sheet.
3. Add the sheet and continue directly to recognition. Additional pages can be
   uploaded later and stay grouped with the song.
4. Review the digital sargam draft beside the photograph and correct anything recognition
   missed.
5. Save the reviewed version and switch between the original photograph and the
   digital copy whenever you play.
6. Select another Concert/Alto key when a transposed view is needed. The original
   transcription remains untouched.

Recognition is intentionally followed by human review. Pencil marks can be faint,
and details such as a dot, short underline, or curved grouping can change the meaning
of a passage. The musician remains the final authority.

## Faithful digital notation

The app preserves the notation as it appears on paper, including:

- sargam notes: S R G M P D N;
- flats, the sharp form of M, and upper- or lower-octave dots;
- holds, rests, barlines, repeats, and curved note groups;
- section headings, free-rhythm runs, endings, directions, and annotations;
- Sinhala lyric fragments written with the music;
- the original line order, spacing, and punctuation as closely as possible.

The saved transcription always represents the sheet in its original scale.
Transposition is a temporary view, so experimenting with another key cannot damage or
replace the reviewed copy.

## What works today

- Installable web app for desktop, phone, and tablet.
- Camera capture and image upload.
- Song gallery with thumbnails and multi-page sheets.
- Full-resolution original-page viewer.
- Handwriting recognition for the project's sargam notation standard.
- Side-by-side correction editor with a live digital preview.
- Visual rendering of accidentals, octave marks, and curved groups.
- Advisory warnings for notation that may have been misread.
- Original and Digital viewer modes.
- Transposition across all 12 keys using Concert/Alto scale pairs.
- Automatic nearest-octave placement plus manual octave adjustment.
- Original photographs stored without resizing or rewriting.

## Project status

SaReGaMaPic has completed **Phase 3**: capture, gallery, recognition, correction,
digital viewing, and sargam transposition are built and working. **Phase 3.4 is
complete**: Google login, revocable server-side sessions, per-user ownership
isolation, abuse controls, and the security release gates are built and verified.
**Phase 3.5 is in progress**: immutable recognition runs, corrected revisions, and
private evaluation metrics form the recognition-learning foundation.

**Phase 4 — Western notation** will add a third viewer mode that converts reviewed
sargam into readable Western staff notation and follows the same key selector. Before
that view is finalized, the remaining musical choices—such as Concert versus Alto
written pitch and how special rhythm markings should appear on
a staff—will be agreed with the musician.

Two practical recognition checks are still in progress: confirming the latest
faint-pencil improvements on real sheets and verifying that correcting a typical page
on the tablet is faster than retyping it.

## Scope and privacy

This is currently an invite-only personal app. It does not include public sharing,
social features, audio playback, or MIDI. Original sheets and reviewed
transcriptions stay isolated in each owner's app storage;
recognition sends the prepared page image to the configured vision service only when
the user chooses **Recognize**.

## Project documentation

Requirements, musical notation rules, technical design, decisions, and the detailed
implementation plan are maintained in the project's private documentation.

---

## License and copyright

Copyright © 2026 Thisara Mallawa Arachchige. **All rights reserved.**

This is proprietary software. It is **not** open source and carries no
permission to use, copy, modify, or distribute it. No license is granted by the
publication of this repository — see the [LICENSE](LICENSE) file for the full
terms. Any use requires the prior written permission of the author.
