# Regions and fit

Layer regions are normalized `(left,top,right,bottom)`, converted to half-open
pixel boxes with an upper-left origin. `anchor` is a normalized x/baseline y.
Arabic defaults to its **last** baseline at 50% height; extra lines grow upward.
English defaults to its **first** baseline at 56%; extra lines grow downward.
Persistent titles/logo never move with phrase length. Dimensions are already
rotation-normalized by the caller; the renderer does not rotate video metadata.

The existing whole-word wrapping algorithm now accepts actual shaped scene ink
metrics. Quotation ornaments attach to their neighboring words, and combining
marks are never split. English wraps separately and explicit segment line breaks
are retained. `max_lines`, `line_spacing`, `safe_margin`, `alignment`, preferred
`font_size` and `min_font_size` are explicit. `fit=wrap` never shrinks; `shrink`
tries bounded sizes down to the configured readable minimum and then fails.
No text, diacritics or meaning is clipped/truncated. Baselines remain stable.

`FitError.details` returns actual/allowed boxes, final candidate font/line count
and suggestions (`split_cue`, `enlarge_region`, `choose_smaller_preferred_font`).
`plan_scene` performs real shaping/ink measurement without writing images. Effects,
inline markers and safe margins belong to the measured fit envelope. Titles and
logos have independent zones; contain fitting preserves image aspect and rejects
anchors that put an image outside its zone. Sizes scale from 576 pixels wide;
landscape/narrow canvases may need an explicitly adapted profile. Cue semantics,
duration and resegmentation decisions remain in QuranScribe.
