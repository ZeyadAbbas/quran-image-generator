# Independent Quran decorations (renderer 0.3.10, schema 1)

Existing requests retain `decoration_layout: "legacy"` and their current pixels.
Opt into `"elements"`, supply a `quotation_style`/`marker_style`, select a `quotes`
or `markers` font asset, or change an individual ornament toggle to use the new
source-associated layout. It requires RTL Quran paragraph direction; unsupported
direction returns a field diagnostic rather than placing an ending incorrectly.

```json
{
  "color": "#FFFFFF",
  "decoration_layout": "elements",
  "quotation_style": {"color": "#00CCFF", "outline_width": 0},
  "marker_style": {"color": "#FFD700", "opacity": 1},
  "quote_open_enabled": true,
  "quote_close_enabled": true,
  "marker_placement": "adjacent"
}
```

Quotation and marker styles independently control fill, alpha, outline, shadow,
font face/axes/features/language, pinned fallback, direction and x/y `offset`.
Omitted fields inherit body choices. A separately selected font starts with its
own default face/axes/features instead of receiving axis tags from an unrelated
body font. `quotes` and `markers` assets use the ordinary pinned local font
selector; `decorations` remains a shared-font fallback for existing callers.

Request-level `quotations` and `verse_numbers`, individual opening/closing toggles,
element `enabled`, and body `outline_width` are distinct controls. In elements
mode body `opacity` governs body pixels; ornaments/numbers inherit it unless
their own opacity overrides it. No additional combined-layer alpha is applied.
`quote_open`/`quote_close`, `decoration_scale` and `quote_spacing` retain their
glyph/relative-size/reference-spacing meanings. Number choices use
`numeral_system`, `marker_prefix`/`marker_suffix`, `suffix_scale`, `suffix_spacing`
and `suffix_offset` consistently for every ending. `offset` adds reference-pixel
x/y adjustments. Legacy inline offset scaling during shrink is preserved only
in legacy mode; elements use reference-pixel offsets consistently.

Every generated marker has an explicit occurrence, surah, ayah, source-word end
and cue-character end from verified spans. It is never discovered by matching
digits or ornament-looking strings in body text. A partial phrase has no invented
ending, separate `0:0` basmala is unnumbered, and repeated completed spans receive
separate marker IDs. Each marker wraps as one unit with its final source word.
`adjacent` places it immediately at that real ending; `after_quote` moves only the
final completed ending after the closing ornament. Source-reference labels are
a separate metadata primitive, rather than substitute ayah markers.

The whole decorated line, including offsets/effects, is aligned and fitted.
Baseline rhythm, source-addressed breaks, readable shrink and max-lines still
apply. `elements` report IDs, kind, text, source associations, font size/hash,
baseline position, glyph/effect boxes and complete effective styles. The verified
cue `arabic` and binding hashes remain unchanged. Inspection reports inherited
versus explicit nested fields. Output is one combined transparent Arabic asset;
cropped offsets reconstruct it exactly. No gradient/artwork family or timed
highlighting is implied by these controls.

Caption Studio exposes separate font selectors, opening/closing toggles,
**Quotation color…** and **Verse-number color…**, plus JSON controls for the full
element styles. All fields round-trip in ordinary requests/profiles.
