# Six-reference caption regressions

`tests/fixtures/captions/six-references.json` contains small authored caption
plans for all six creator-owned clips. It pins media SHA-256, source URLs,
Simple corpus identity, mapping revision, bundled font hashes, exact Arabic
slices and test-only English bindings. Repetitions are separate occurrences
sharing assets. The reference frames at two seconds are comparison candidates;
their content/timing and the original assets still require creator approval.

The checked-in [contact sheet](../tests/fixtures/captions/contact-sheet-preview.jpg)
shows verified local source frames beside newly rendered captions on a blank
background. Source video already has burned-in captions. It is never used as
the background for a new caption. No source video is distributed here; missing
original logo remains visibly absent rather than replaced with an invented one.
The sheet and six small PNG masks are marked **needs_review**, not approved
before/after evidence or identification of the original translation edition.

Reproduce the sheet without HTTP using optional local media:

```
python scripts/caption_review.py --output-dir "review output" --media-directory "/local/reference/videos" --ffmpeg ffmpeg
```

Files must be named `<clip_id>.mp4` and match every recorded checksum; changed
or missing media fails explicitly. Omit `--media-directory` to generate blank
source panels and inspect renderer output alone. The report records runtime,
profile/font hashes, source frame hashes and Arabic identities. FFmpeg is only
an optional development tool for extracting review frames, not a renderer
dependency or a video export pipeline. QuranScribe owns timing and final video.

The renderer tests use real ImageMagick/RAQM and no external HTTP. They check
all six sets, repeated 17:13/2:44/5:23, 39:30 and 5:73 terminal words, quotes,
true verse-end markers, independent English, stable persistent titles, actual
alpha bounds, effect containment, hashes and readable wrapping/shrinking.
Existing tests also cover basmala/joined words, caller-supplied logo containment,
missing glyphs, corrupted assets, overflow and opaque still-image rendering.
Installed-wheel CI on Windows/Linux compares public Python with a separate
JSON process outside the checkout, including paths with spaces and offline
translation snapshots. Tests cover portrait, doubled portrait, narrow and
explicitly adapted landscape regions.

Pixel comparison is separate from exact source-reference identity. For the
runtime recorded in `goldens/runtime.json`, the small bundled masks allow at
most two pixels of alpha-bound drift and 2.5% mean error within the union of
ink bounds, for alpha and composites on both black and white. Invisible RGB
does not influence the comparison. A deliberately shifted caption, clipped
title or opaque background must fail. Another raster runtime gets structural
checks (16-pixel bounds drift, 30% integrated-alpha tolerance); it does **not**
inherit pixel approval from that baseline. Capture and review its own baseline
before claiming pixel reproducibility. Fonts are always content-hash pinned.

Regenerate authored content only with `scripts/build_caption_fixtures.py`,
then inspect exact Arabic/translation/provenance changes. Do not automatically
replace golden PNGs after a test failure. The renderer issues cover capabilities
and technical regression gates; production content/visual approval belongs to
the caller and is not fabricated by tests. The four explicit 17:13 spelling
equivalences are recorded separately; the other 4,194 boundary groups remain
on the exhaustive mapping review list, with typed errors for partial selection.

## Creator-font comparison

The later font discovery is an example in `scripts/reference_caption_options.py`, reviewed with
`scripts/creator_font_review.py`. It uses the identical me_quran body/title font,
AL-QURAN-ALI ornaments/numerals, Arial English, and Quran Surah 01's `y` emblem.
This is a separate revision from the bundled preview; existing golden masks are
not replaced or treated as creator-approved pixels.

```
python scripts/creator_font_review.py --creator-font-directory "/local/fonts" --latin-font "/local/Arial.ttf" --media-directory "/local/reference/videos" --output-dir "outputs/creator-font-review" --ffmpeg ffmpeg
```

The script checks all six video hashes, exports transparent overlays and local
request options with pinned font paths, and saves enlarged source/preview regions
for titles, verse/caption, and logo. It records runtime, layer plans, both font
checksums, and exact Arabic. The two multi-line English examples retain explicit
reference line breaks. English remains an authored review fixture with its
existing provenance, not an approved production translation dataset.
No source media or proprietary font binaries are committed. Review the generated
`creator-font-comparison.jpg` and `review.json` before approving a final match.

## Per-layer matched regression and local handoff

`tests/fixtures/captions/matched` holds 30 small rendered layer masks, exact asset
hashes, request/content/font signatures and a recorded raster runtime. They are
a **technical baseline marked needs_review**, not approved reference pixels.
Each verse, English caption, Arabic title, English title and symbol-font emblem
gets its own pixel/bounds/alpha gate; losing a small logo cannot be hidden by
larger caption bounds. Deliberate missing, shifted and wrong-color layers fail
in ordinary CI. Real bundled-font scene/contract rendering still runs on Linux
and Windows; original creator/system font binaries are not distributed to CI.

Run the actual matched-font gate and generate local consumer requests:

```text
python scripts/reference_handoff.py --font-directory "/local/fonts" --latin-font "/local/Arial.ttf" --output-dir "outputs/quranscribe-handoff"
```

It checks every authored cue at both portrait sizes (**64 layouts**), separately
checks all **30 layers**, and compares each of the six first-cue Python results
with a separate JSON process. Run the absolute script using the fresh installed
renderer interpreter from outside the checkout, with no source-tree PYTHONPATH.
The output includes six full requests, six first-cue examples, the handoff,
layout matrix and comparison report. There are no ASR/video export dependencies.

The same gate is available in pytest by setting `QIG_REFERENCE_FONT_DIRECTORY`
and `QIG_REFERENCE_LATIN_FONT`. Without those explicit caller-font paths that
optional test is skipped; CI's generic rendering and defect gates still run.
If raster identity matches, each layer must stay within two pixels and 2.5%
alpha/black-and-white composite error. A different runtime receives a separately
reported structural check (four pixels and 10% integrated-alpha tolerance), not
pixel approval. Different font/text/style hashes fail regardless of runtime.

The only baseline-writing path is the explicitly supplied `--capture-baseline`
option. It must be inspected and committed deliberately, never run as a repair
after a failing comparison. Bulk videos and source fonts remain outside Git.
