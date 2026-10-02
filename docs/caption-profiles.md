# Caption profiles and effects

`CaptionProfile` round-trips structured JSON through `export_profile` and
`import_profile`, with ID/revision, approval state, per-role styles and asset
provenance. `creator_profile(scene)` is `islamstruebeauty` revision `1-preview`,
explicitly **needs_review**: bundled me_quran/Noto Latin fallback fonts are not
identified creator fonts. The creator's original logo, fonts and translation
source must be imported and licensed/approved before claiming a reference match.
All asset hashes and profile bytes belong in export reproducibility metadata.

Fields control white fill, opacity, outline width/color, shadow offset/blur/color
and shadow opacity independently. No word highlighting or text box is introduced.
Effects use actual glyph alpha, preserve fractional edges, and are included in
the conservative fit envelope. Dimensions scale from a 576-pixel reference width.
Font cmap coverage is validated before shaping; missing glyphs fail explicitly.
RAQM shapes complete lines, retaining connected Arabic, ligatures and diacritics.

`decorate_excerpt` inserts Quran quotation ornaments into display text only;
the manifest's verified source text remains unchanged. The Arabic-Indic ayah
number appears only for a true numbered ending. On single-span cues it is a
separate white run at `suffix_scale=.55`, on the left/reading end of the closing
quotation at the same baseline. Multi-span cues retain each true number beside
its span in the shared run. This position/size is a reviewable starting profile,
not a claim of creator approval. The old blue/gold still-image markers are separate.

Profiles are integration JSON, editable in the public Python/machine API. The
existing Tk GUI's YAML controls remain for still images; loading/saving those
settings does not alter a separately saved caption profile.
