# Source-word emphasis states (renderer 0.6.0)

Schema 1 now has an opt-in `word_emphasis` configuration and per-cue `word_states`.
The public representation is **selection_state_variants**, contract version 1.
Each state replaces the Arabic layer's PNG and reuses the same other assets and
approved layout. No timestamps, scheduler, transcript matching, or video encoder
are added. Old requests keep their pixels and behavior.

Query `capabilities("pillow")` or the `capabilities` operation and check both
`word_highlighting` and `word_emphasis.supported`. The descriptor also appears in
`style_contract.word_emphasis` and includes configuration/state schemas, defaults,
units, atomic policy, and limits. This capability requires **Pillow with RAQM**.
ImageMagick remains supported for ordinary captions; an opted-in emphasis request
reports `unsupported_word_emphasis_backend` before attempting its layout.

## Request and source identity

Add this to an otherwise valid [batch request](render-api-v1.md):

```json
{
  "word_emphasis": {
    "mode": "fill",
    "active_color": "#FFFFFF",
    "inactive_color": "#595959"
  },
  "cues": [{
    "cue_id": "recitation-1",
    "spans": [{"surah": 31, "ayah": 9, "word_start": 1, "word_end": 5}],
    "word_states": [
      {"state_id": "all"},
      {"state_id": "current", "default_weight": 0,
       "words": [{"span_occurrence": 0, "source_word": 2, "weight": 1}]},
      {"state_id": "recited", "default_weight": 0,
       "words": [{"span_occurrence": 0, "source_word": 1, "weight": 1},
                 {"span_occurrence": 0, "source_word": 2, "weight": 1}]},
      {"state_id": "fading", "default_weight": 0,
       "words": [{"span_occurrence": 0, "source_word": 2, "weight": 0.4}]}
    ]
  }]
}
```

Omit color overrides to use the existing Quran fill as active and its encoded
sRGB channels multiplied by 0.35, rounded to integers, as inactive. Weights are
linear between those colors; they do **not** fade glyph alpha or effects. Both
colors accept exactly `#RRGGBB`. Omit `word_states` for an `all` state with weight
1 everywhere. Omit `word_emphasis` to use the original static API.

`span_occurrence` is the zero-based index in this cue's `spans`. `source_word` is
the inclusive one-based canonical source position in its verse, not the displayed
token's index. The enclosing cue supplies `cue_id`; surah/ayah are verified from
that span. Repeated passages retain distinct occurrence selectors. Duplicate
selectors/state IDs and selectors outside the cue fail with exact JSON pointers.

Python accepts the same dictionaries or typed `requests.BatchRequest` with
`word_emphasis`, `CueRequest.word_states`, `WordState`, and `WordSelection`.
The published request/response JSON schemas include these fields. Caption Studio
preserves them when opening and saving a request; video controls belong to the
consumer.

## Shared layout, indivisible units, and geometry

`layout`, `validate`, `inspect`, and cue-bearing `preflight` resolve the same word
units and selection errors without producing PNGs. As before, preflight may
create/probe a requested output directory. `render_batch` publishes the states.
The cue's `word_emphasis` response contains:

- `layout_id`, a SHA-256 identity of the approved plan, canvas, runtime, source
  associations, and actual prepared mask fonts. Selection weights and paint
  overrides never refit the caption or change this identity. Identical repeated
  cues can share the layout/assets while keeping different member cue IDs.
- `units`, each with `unit_id`, canonical `members`, `atomic`, `atomic_reasons`,
  and `display_ranges` into the actual decorated Arabic layer. Character ranges
  are half-open Unicode codepoint offsets; the verbatim displayed text is echoed.
- Per-unit `parts`, recording line index, existing body run ID/full text,
  half-open run codepoint ranges, actual half-open `ink_bounds` in output pixels,
  and the derived `mask_font_sha256`. Bounds include belonging diacritics and ink
  extending beyond an advance. A source unit wrapping onto several lines has
  several parts. These are geometry/provenance records, not exported masks.
- Per-part `backgrounds`, with output-pixel `rect`, line index, and effective
  `corner_radius_pixels`.
- `states`, with stable `state_id`, normalized per-unit `weights`, and ordered
  `asset_ids`. Use that complete ordered list to compose a state. The original
  cue `asset_ids` and `layers` still describe its ordinary static caption.

The bridge's joined source/display words, inseparable shaping clusters, and
physically overlapping word ink are atomic. Every member must receive the same
weight, including unselected members resolved through `default_weight`.
`atomic_word_split` reports the members and reasons rather than inventing a split.
Build selections from the returned units, not by splitting Arabic on spaces.

`atomic_evidence` records why a shaping/ink union was required: the full run,
prepared and mask font hashes, contributing half-open character ranges, and
whether a consumed initial, jointly restored missing ink, or shared fill pixels
caused the union. Source/display groups report their verified mapping revision
and source/display ranges. `atomic_word_split` also includes this evidence.
These are conservative raster ownership tests, not exported HarfBuzz cluster IDs.

Quotation ornaments and verse markers are independent. In legacy inline runs,
separate word and ornament glyphs can share antialiased pixels: **static ornament
pixels take precedence** and remain unchanged. Each part reports the count as
`protected_decoration_pixels`. Background bounds still cover the complete word.
A glyph that cannot be safely separated from a decoration reports
`word_decoration_atomic`; use independently positioned decoration elements or a
different covering font/layout. Titles, branding, translation tracks, source and
edition labels, and existing layer/group panels use their original asset IDs.

## Paint and compositing

`mode` is `fill`, `background`, or `both`. Background-only mode preserves text fill
and rejects active/inactive text-color overrides. Its defaults are:

```json
{"background": {"color": "#FFD54F", "opacity": 0.35,
                "padding": [0.15, 0.08], "corner_radius": 0.12, "unit": "em"}}
```

Padding is `[horizontal, vertical]`; units are fitted Arabic em or final
`output_pixels`. Bounds expand outward with floor/ceil. The radius is clamped
to half the shorter rectangle side. Background alpha is opacity times word
weight times Arabic opacity. Overlapping rectangles take maximum alpha instead
of accumulating darkness. Backgrounds paint behind the unchanged Arabic effects
and fill; other decorations/layers keep their existing compositing order.
`word_background_overflow` reports bounds and allowed region if padding cannot
fit the original canvas/layer/group region. It never silently shrinks or reflows.

The original full-line glyph alpha drives the **single** fill operation. Outlines
and shadows render once with the original geometry and style, including fractional
alpha. Selection variants are ordinary checksum-verified, content-addressed PNG
assets with straight alpha, sRGB colors, crop offsets and actual effect bounds.
Default all-active fill states reuse the original Arabic asset directly. Use
ordered state IDs/offsets as published; do not overlay whole variants on each other.

Public helpers in `quran_image_generator.word_emphasis`:

```python
with compose_word_state(response, 0, "current") as current:
    current.save("current.png")  # verifies every referenced PNG checksum

with compose_word_state(response, 0, "current") as a, \
     compose_word_state(response, 0, "recited") as b, \
     interpolate_word_states(a, b, 0.5) as frame:
    frame.save("fade-midpoint.png")
```

The consumer supplies progress and endpoints from the **same** immutable layout
and canvas. Interpolation uses premultiplied alpha and linear encoded-sRGB channel
weights; it is not a linear-light color-space conversion. Equal endpoint alpha
stays identical, so effects are not doubled. Exact 0/1 endpoints are copies.
Changing background coverage legitimately interpolates alpha too. Freeze/pin the
request, manifest, runtime/font identities, layout ID, and assets for exports.

See [the runnable public integration example](../examples/word_emphasis.py).
Consumers own current/cumulative/all modes, timing, caption resets, fades, and
atomic/no-timing policy. Submit at most 32 states per cue; longer timelines can
render bounded jobs from the same pinned layout and verify matching `layout_id`.
There are at most 128 source/display groups per cue, 4096 mask probes, 64 MiB
mask working/storage bytes per cue, 128 MiB mask bytes per batch, 512 assets and
512 MB PNG bytes per batch. Cancellation/deadline checks run between mask probes
and states. Do not ignore resource, changed-input/cache, or partial-job failures.

## Full-context ownership extraction

Ownership comes from the **actual prepared Pillow font bytes**, including selected
face, axes, fallback, and extra spacing. An in-memory private ranged GPOS feature
translates excluded glyphs out of a bounded ink tile after positioning, while
shaping the complete original run with the original features/language. No word
substring is shaped alone, and no advances, substitutions, glyph outlines, source
wording, baselines, wrapping, or group positions are changed. The feature-disabled
font must reproduce the normal raster exactly, and selected units must reconstruct
the complete original ink exactly before they are accepted. Horizontal scaling
uses the original whole-run crop and resampling grid. Unsafe decompositions fail
explicitly instead of returning approximate word positions.

Full-run boundary probes also check consumed source initials against the font's
nominal glyph outlines. In fonts such as DigitalKhatt Madina, cursive positioning
can drag a singleton probe out of the tile even when all dependencies stay inside
the same source word. A second full-run diagnostic disables only `curs` to
distinguish this from consumption across a source boundary. Diagnostic pixels
never enter rendering or geometry: original features, masks and exact full-ink
reconstruction remain mandatory. This fixes the source-initial failure at 35:1
words 11–13 and false adjacent-word unions reported in #95, without changing
fonts, diacritics, quotation colors, or ordinary/all-active pixels.

A real cross-word ligature can still belong entirely to its first word, with
disjoint masks and a consumed initial even without cursive attachment; those
words remain atomic with their contributing ranges recorded. Physically shared
word ink and joined Uthmani display words also remain atomic. An unresolved static
decoration boundary fails explicitly with source members, run/static ranges,
font identities and run position. Use the actual returned groups for each pinned
font/layout; there is no universal list of atomic source words. All valid Fatir
excerpt pairs cited in #95 are separate in the tested signature preset. The
report's 35:3 words 26–27 are outside that verse's canonical 22 words and remain
`invalid_reference`.

For exact canonical Simple boundaries inside joined Uthmani display words, choose
explicit `arabic_script="simple"`; see [verified Simple display](source-references.md#verified-simple-display).
No fallback or source expansion occurs. Both editions share the emphasis/state
contract and preserve translations and static layer identities.
