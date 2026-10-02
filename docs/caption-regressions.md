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
replace golden PNGs after a test failure. Original font/logo licenses, approved
phrase translations, reference measurements and creator signoff remain the
gates for closing issues #39, #40, #42 and #46. The four explicit 17:13 spelling
equivalences are recorded separately; the other 4,194 boundary groups remain
on the exhaustive mapping review list, with typed errors for partial selection.

## Creator-font comparison

The later font discovery is implemented by `creator_assets` and reviewed with
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
