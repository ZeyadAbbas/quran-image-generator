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

## Discovered creator fonts (0.2.1)

`matched_creator_configuration(font_directory, latin_font)` returns request
options for `islamstruebeauty/2-matched`. It discovers exact file bytes recursively
by SHA-256, requires explicit Arial Regular, and never copies or substitutes a
local font. `matched_creator_titles(surah)` supplies cue title overrides for the
spellings visible in the six references. Merge these options into a normal v1
request; source references and approved phrase bindings keep their existing form.

| Content | Font / input |
| --- | --- |
| Quran and Arabic title | me_quran; same checksum as the bundled Quran font |
| Verse quotation ornaments | AL-QURAN-ALI, `{` and `}` (also its U+FD3E/FD3F glyphs) |
| Small verse number | AL-QURAN-ALI, ordinary typed digits inside `(43)` |
| English title and caption | Caller-selected Arial Regular |
| Bottom Quran emblem | Quran Surah 01, Latin `y` (U+0079) |

The supplied B Arabic Style and Borders Islamic fonts do not match these roles.
Parentheses in AL-QURAN-ALI are ordinary round parentheses; braces produce the
decorated quotation strokes. Digits are kept as ordinary input because that font
maps them to the Arabic numeral glyphs visible in the source. The emblem is a
complete symbol-font glyph, shaped and exported as a persistent text layer.

An optional `decorations` asset has the same path/hash/license/attribution contract
as other font selectors. It shapes quotes and small numbers independently of the
Arabic body, including numbered endings inside multi-span cues. Its checksum is
captured in every layer plan and verified again at rendering and publication.
`quote_spacing`, `suffix_spacing`, `suffix_offset`, `decoration_scale` and
`horizontal_scale` control the measured geometry; fractional font sizes are valid.
Horizontal adjustment resizes a complete shaped line, preserving connected Arabic
and all source text. Default profiles retain their existing geometry and fonts.

The profile is **needs_review**. Font identity and visual matching do not approve
translation editions, cue timing, or a final video. Creator-supplied font terms
remain attached to the local asset records; Arial and the discovered fonts are
not newly distributed in the package. See [the reference workflow](caption-regressions.md).
