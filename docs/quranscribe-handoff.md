# QuranScribe handoff: request the sample-video composition

Use **quran-image-generator v0.3.5**, **JSON schema 1**. Install the renderer in
its own environment as described in [integration-install.md](integration-install.md).
QuranScribe requests static transparent layers, then controls every occurrence's
timing, fades and video composition. Preserve the input frames and audio.

The renderer has general capabilities, with a plain default. No QuranScribe
mode, creator preset name, default translator or sample-specific app setting is
installed. The `profile` object below means **caller-supplied layer styles**.
Its ID/revision are provenance; changing the ID alone changes no pixels.

## Copyable requests

[reference-style.json](../examples/captions/reference-style.json) contains the
complete measured style and asset selectors, with portable placeholder paths.
[reference-request.json](../examples/captions/reference-request.json) is a complete
31:9 prefix/repeat request with an explicitly authored English fixture.

Replace every font path with a local renderer-host path. Replace the Arial hash
with the SHA-256 of the explicitly selected **Arial Regular** file. All other
font hashes are the discovered source files, not filenames or a system fallback.
On the creator's Windows machine, the local handoff directory also contains a
ready-to-run request with real paths. For containers, use paths inside the mounted
input directory. Nothing in the request instructs the renderer to find assets
inside QuranScribe or modify app defaults.

```text
quran-caption-render --capabilities
quran-caption-render --preflight --request reference-request.json
quran-caption-render --request reference-request.json
```

Preflight returns the real layouts without producing images. It must verify
fonts, glyphs, content, binding readiness, fit and writable output before export.
Capabilities must report schema 1, a supported 0.3.x renderer and the pinned
source corpus/mapping. The Python equivalent accepts **all** the same options:
`BatchRequest`, `CueRequest`, `Canvas`, `AssetSelector`, `TranslationSnapshot`,
`CaptionProfile`, `BindingDataset`, `RenderRequest`, `execute_request`.
`RenderRequest.from_dict(json_payload)` is also a supported public entry point.

## Exact font inputs and measured geometry

| Layer | Font/input | SHA-256 |
| --- | --- | --- |
| Verse and Arabic title | me_quran | `65464072d7c754baa642a4f5031d6cb3b6311cf06ad1826f8fd317f98283096d` |
| Quote ornaments and small ayah numbers | AL-QURAN-ALI | `57c70bf2efe34444a54ab065173c3d0152e7dd4dc320926fc34e24c85e82d3cd` |
| English title and phrase | Explicit Arial Regular | Compute from the actual local file |
| Bottom emblem | Quran Surah 01, Latin `y`, U+0079 | `8c989d70fcd8b94829f3fe3338d88f71e764840499494b4d41aa2ebd78fbc027` |

Fonts remain caller-supplied with their notices. The me_quran file is byte-identical
to the bundled verse font. English Arial is the closest measured visual match;
the original project is unavailable. In AL-QURAN-ALI, `{` and `}` create the quote
ornaments; `(` and `)` are ordinary parentheses. Pass ordinary ASCII digits in
`(43)` with `numeral_system="latin"`; the font produces the source numeral glyphs.
The renderer generates numbers only from validated `ends_ayah`, never caller text.
Set `assets.logo.glyph="y"`; this creates a reusable shaped symbol-font layer.

Styles are scaled from **576-pixel reference width**. Coordinates are normalized
0..1 with the origin at the top left. Anchors locate a text baseline, rather than
its bounding-box center. Use the complete saved request; it pins the measured
overrides to this release.

| Layer | Size at 576 wide | Anchor | Region | Additional settings |
| --- | --- | --- | --- | --- |
| Arabic phrase | 25.25, minimum 24 | `[0.5, 0.503]` | `[0.025, 0.28, 0.975, 0.53]` | Horizontal scale 1.14; max 4 lines; shrink; last baseline |
| Arabic title | 23.5, minimum 20 | `[0.5, 0.161]` | `[0.05, 0.12, 0.95, 0.173]` | Horizontal scale 1.08 |
| English title | 14.5, minimum 12 | `[0.5, 0.1865]` | `[0.05, 0.17, 0.95, 0.205]` | Caller title override |
| English phrase | 14.5, minimum 12 | `[0.5, 0.542]` | `[0.12, 0.525, 0.88, 0.68]` | Max 3 lines; spacing 2; first baseline |
| Emblem | 59.25 | `[0.5, 0.9253]` | `[0.4, 0.86, 0.6, 0.97]` | Persistent glyph layer |

All sample layers use white fill, opacity 1, outline width 0 and shadow opacity 0.
Outline/shadow remain independently available when explicitly requested for other
styles. Arabic decorations use `quote_open="{"`, `quote_close="}"`,
`decoration_scale=1.14`, `suffix_scale=0.435`, `suffix_offset=-4`,
`suffix_spacing=5`, `marker_prefix="("`, `marker_suffix=")"`.
Use `titles=true`, `quotations=true`, `verse_numbers=true`, `cropped=true`.

Provide per-cue Arabic/English title overrides. The observed English labels are
`Surah Luqman`, `Surah Al-Isra`, `Surah Al-Baqarah`, `Surah Al-Ma'idah`, and
`Surah Az-Zumar`. Arabic labels are `سورة` followed by the verified chapter name.
Split title-bearing cues at chapter changes; use `title_surah` for separate
basmala. The renderer keeps titles/emblem persistent and reuses their assets.

## Content and English

Source spans are **inclusive, 1-based Simple-word references** with the exact
corpus identity reported by capabilities. Pass each spoken occurrence as its own
unique cue ID, even for identical spans. Do not transfer ordinal positions into
Uthmani text yourself. The renderer resolves the pinned bridge to verbatim Uthmani
and returns exact text/character ranges. A `mapping_boundary` failure requires a
reviewed mapping or selection boundary; never round it or substitute raw text.
Separate unnumbered basmala is `[surah=0, ayah=0, word_start=1, word_end=4]`.

English comes from an explicit source-preparation stage. The machine interface
now exposes `translation_catalog` and `prepare_translations`; see
[the operation contract](render-api-v1.md). The caller selects an edition, supplies
source notices, saves the returned checksum-pinned snapshot and exact dataset,
then renders offline. Whole ayahs receive verbatim unreviewed English; partial
phrases still require reviewed exact wording. For a visible draft, use `review`
with `preview_unreviewed_translation=true`. Warnings/review state stay explicit.

Production English must be a reviewed exact binding to those ordered spans. Use
`translation_policy="required"`, an explicit `translation_binding_id` and either
`translation_dataset` or a pinned `translation_snapshot` (not both). Import/export
with the public [bindings API](phrase-translations.md); snapshots never fetch or
refresh during rendering. Preserve source/provider/resource/version/translator,
license/attribution, source hash, Arabic hash, mapping revision, review state,
reviewer, segments and edit flag. Changed wording/reordered English requires
`edited=true`. Line breaks alone do not make a verbatim caption an edit.

The source translation edition is unconfirmed. The included English is explicitly
authored development material; it is not a production approval or license claim.
For the actual reference wording, import the creator's reviewed segments and
retain that distinct provenance. Never proportionally slice a whole-ayah English
translation or silently attach the whole verse to a short Arabic phrase.
Missing/unreviewed bindings fail required export. Explicit `review` requests
produce an Arabic-only preview with review warnings; `none` is Arabic-only.

The observed two-line first captions retain these exact line breaks:

```text
39:29 words 1–7:
Allah sets forth the parable of a slave owned by
several quarrelsome masters,

5:72 words 1–10:
Those who say, "Allah is the Messiah, son of Mary,"
have certainly fallen into disbelief.
```

These breaks live in binding segments, independently from Arabic wrapping.
Other long authored fixture phrases exercise fit, not exact reference wording.

## Consume returned assets

Require top-level `complete` and every cue `ready` for an approved production
plan. `needs_review` is an explicit preview state; preserve it instead of marking
it approved. The measured reference style stays review-required until the caller
records its visual review. `require_approved_profile=true` enforces that gate.

Resolve PNG paths beneath `job_directory`, verify SHA-256, dimensions and manifest,
then composite **straight alpha, sRGB** at the returned `offset` on a canvas of
the requested dimensions. Cropped PNGs use actual offsets; do not center them
again. Use each cue's `asset_ids`. Retain ordered cue occurrences and metadata:
identical assets may be reused, identical occurrences may not be deduplicated.
Persistent title/logo assets continue through caption-free intervals (one
reference has no central caption at 16s); do not hide them with phrase captions.
Honor `z_order`. Preview and MP4 must use the same assets, placement and timeline.

QuranScribe owns intervals, silence gaps, fades, chapter transitions and encoding.
Keep exported phrases static with no word highlighting. GUI word highlighting
remains a separate transcript-review concern. Do not render onto the already
burned-in sample videos: compare separate source crops with blank/synthetic
composites. The six-video style comparison and regression workflow are documented
in [caption-regressions.md](caption-regressions.md).

Errors are typed, with retryability and overflow diagnostics. Stop on missing or
changed fonts, missing glyphs/shaping, unresolved spans, stale bindings/snapshots,
unreadable fit or required-layer failure. Per-cue partial jobs are opt-in and
must not become silent successful exports. Caller-owned `job-*` directories and
snapshots must remain while saved plans reference them.

Renderer issues #35–#46 cover these static capabilities. QuranScribe issues
[#17](https://github.com/ZeyadAbbas/QuranScribe/issues/17) through
[#21](https://github.com/ZeyadAbbas/QuranScribe/issues/21) own occurrence planning,
the installed client, composition, GUI review and final-video regression gates.

The renderer's own [Caption Studio](caption-studio.md) exposes these same general
options to every user. Open a complete measured request with
`quran-image-generator-gui --request "reference-request.json"` to inspect or
customize each layer, asset and binding, then save ordinary request JSON. There
is no special QuranScribe mode or preset. The renderer GUI is also useful for
visual review before QuranScribe applies its own timing and video composition.
Measured fonts/layout establish a reproducible request, not pixel identity,
semantic translation approval or acoustic timing approval of a final video.
