# Caption style editor handoff to QuranScribe

The renderer portion of the 2026-10-11 audit is implemented through **0.3.13**,
with backward-compatible **schema 1**. QuranScribe can build its customer editor
over the installed public API. This document assigns every requested control;
it does not implement QuranScribe's product UI or upgrade its renderer pin.

The audit baseline was 0.3.5. Install an immutable reviewed 0.3.13 commit or built
wheel using the [independent install guide](integration-install.md), then query
actual capabilities on that host. Package versions do not imply a release tag
or PyPI publication. The unchanged measured sample requests remain in the
[sample-video handoff](quranscribe-handoff.md).

## Delivered renderer capabilities

| Customer control | Current renderer contract | Tracking / version |
| --- | --- | --- |
| Control discovery, defaults, units, bounds, exact errors and preview inspection | Versioned `style_contract`; request schema; `inspect`; JSON Pointer diagnostics | [#74](https://github.com/ZeyadAbbas/quran-image-generator/issues/74), 0.3.7; [contract](style-contract.md) |
| Extra word spacing, baseline line height, safe tracking, chosen source-word breaks | Em spacing/height, Latin grapheme tracking, verified source occurrence/word hints | [#75](https://github.com/ZeyadAbbas/quran-image-generator/issues/75), 0.3.8; [typography](caption-typography.md) |
| Font faces, metrics, coverage, axes, features/language and pinned fallback | `inspect_fonts`; checksum-pinned selectors; deterministic face/axis materialization; explicit whole-layer fallback | [#76](https://github.com/ZeyadAbbas/quran-image-generator/issues/76), 0.3.9; [fonts](font-controls.md) |
| Independent quotation and true verse-end decoration style | Opt-in element layout; independent colors/effects/fonts/scales/offsets/toggles; source-associated endings and repeats | [#77](https://github.com/ZeyadAbbas/quran-image-generator/issues/77), 0.3.10; [decorations](decoration-elements.md) |
| Per-language or shared readability panels | Line/block/region solid panels, padding, rounded corners, border and shadow; group backplates | [#78](https://github.com/ZeyadAbbas/quran-image-generator/issues/78), 0.3.11; [panels](caption-panels.md) |
| Real ink/block positioning, multilingual flow and combined fit | Explicit anchors/scale basis; ordered flow; coordinated ratios/minima; collision/overflow diagnostics; revalidation helper for common sizes | [#80](https://github.com/ZeyadAbbas/quran-image-generator/issues/80), 0.3.12; [groups](caption-groups.md) |
| Independently styled languages/editions and separate references/labels | Stable instance IDs; per-track exact reviewed binding revision, dataset/snapshot/font/style; truthful source references; bounded approved annotations | [#79](https://github.com/ZeyadAbbas/quran-image-generator/issues/79), 0.3.13; [tracks](translation-tracks.md) |
| Ordinary text visibility, fill/alpha, stroke/shadow, preferred/minimum size, max lines, horizontal scale and normalized region | Existing per-layer styles, preserved by the additions above | [profiles](caption-profiles.md), [fit](caption-fit.md) |
| Arabic/Latin titles and image or font-glyph branding | Existing independent/persistent roles with pinned assets and recorded terms | [overlays](overlays.md) |
| Reference-only Quran, offline reviewed translations, repeat deduplication and exact exported PNGs | Canonical/source identity; reviewed bindings; immutable manifests/assets; cropped offsets; progress/cancel/deadline and failure policies | [references](source-references.md), [translations](phrase-translations.md), [batch ownership](batch-ownership.md) |

These additions are normal request data, not hidden presets. Legacy single-
translation, baseline-anchor and decoration defaults retain their existing
behavior. The native Caption Studio edits the same schema; its advanced track,
annotation and group collections are currently exposed through JSON dialogs.

### Gate controls against the installed backend

- Nonzero extra word spacing requires native Wand/RAQM. Font feature/language
  overrides require Pillow/RAQM. Discovery states availability and incompatible
  combinations fail explicitly; do not show unsupported controls as working.
- Independent Quran decoration layout currently supports RTL paragraph flow.
  Safe nonzero tracking supports LTR Latin graphemes only. Whole-layer fallback
  preserves shaping context; it does not combine complementary fonts by letter.
- Gradient panels and static/timed word highlighting are not implemented.
  Discovery retains `gradient_panels=false` and `word_highlighting=false`.
- Default dimensions use width/576, with explicit short-side or pixel scaling
  available. Keep effect/font units explicit; minimum sizes constrain joint fit.
- Limits include 8 tracks, 4 annotations and 16 total output layers including
  shared panels, 1000 cues, 32 source spans per cue, 8 MB request data and
  8.5 million canvas pixels. Split larger jobs and respect resource errors.

## QuranScribe ownership

| Product requirement | QuranScribe implementation responsibility |
| --- | --- |
| Visual presets, thumbnails and personal/project styles | Expand to ordinary editable values; duplicate/rename/favorite/reset; versioned storage, import/export, aspect variants and explicit font identities |
| Basic and advanced editor controls | Human units, bounded sliders, linked/unlinked settings, undo/redo, per-section reset and selected-cue versus all-caption scope |
| Font catalog/uploads and asset permissions | Host/select legally usable bytes and terms; pin paths/hashes visible to the renderer; use inspection before saving |
| Language/edition selection and ordering | Prepare/download explicit sources outside rendering; author/review exact phrase bindings; preserve distinct editions; set track IDs, revisions and group order |
| Friendly label and decoration controls | Keep stroke, quotes, actual verse endings and source labels separate; supply approved metadata text and truthful supported formats |
| Drag handles and platform guides | Convert UI positions/margins into normalized regions/anchors; maintain portrait/landscape/square variants and safe-zone guides |
| Responsive actual-video preview | Debounce/cancel; ignore obsolete results; use exact latest renderer assets/checksums and offsets over the chosen video frame |
| Representative stress cues | Include longest Quran/translation, all scripts, multiple endings, partial/repeated ranges, basmala and all active panels/tracks |
| Whole-timeline validation and approval | Inspect/preflight every current cue; review any shrink/overflow; require revalidation after a common-size suggestion or style/font/binding change |
| Immutable preview/export revision | Pin renderer/native runtime, request/style/font/binding identities and use the approved rendered assets for export; style approval never approves wording |
| Timing, title/branding persistence, fades, motion and video-background blur | Own occurrence timeline, chapter transitions, video/audio composition and encoding |

The renderer owns canonical selection and source/display identity, exact binding
validation, font shaping/metrics, static layout/panels/pixels, capabilities and
diagnostics, pinned cache identity and public Python/JSON/native document
behavior. It does not select QuranScribe presets or modify its configuration.

## Concrete integration sequence

1. Pin/install the reviewed renderer and native stack. Check renderer/schema,
   descriptor version and backend field availability; preserve bundled and
   selected source/font/logo notices.
2. Expand product presets into explicit styles. Select/pin covering fonts and
   approved translation bindings; save distinct track/edition IDs and revisions.
3. Build representative requests with explicit flow/safe regions, readable
   minima, enabled instances, reference formats and independent decoration/panel
   settings. Inspect actual resolved geometry before presenting a successful
   preview. The [two-edition fixture](../examples/captions/translation-tracks.json)
   is a test-only offline starting point, not approved production wording.
4. Preview the exact assets over the real video. Track the complete revision;
   invalidate saving/export when anything changes and discard stale responses.
5. Revalidate the full timeline. Fail required/stale/unapproved bindings and
   unusable fonts/fit. A draft remains `needs_review`; a partial batch remains
   partial until its failed cues are handled explicitly.
6. Export using the approved static assets and their offsets/checksums. Keep
   referenced immutable jobs/snapshots alive; compose timing/fades/video/audio in
   QuranScribe. Re-rendering on another native stack requires fresh validation.

## Verification and remaining acceptance

Renderer changes passed the full regression suite on Windows, Ruff/mypy,
wheel/sdist content inspection and isolated installed Python/JSON checks.
GitHub CI gates each implementation on Python 3.10/3.14, lint/types, package
installation, native Windows caption contract and container smoke. Regression
coverage includes source/binding invariants, old defaults, real RGBA fonts and
decoration colors, partial/repeated references, panels, joint fit, per-track
review/provenance, crop recomposition, deterministic identities, explicit
backend/coverage failures and native document roundtrips.

The final renderer suite has **420 passed and 1 skipped**, plus 4 subtests. The
skip needs the caller's exact original reference fonts; their creator-specific
visual approval remains an explicit input. That skip does not establish
production translation semantics or the final video's timing/visual approval.
QuranScribe must upgrade its own pin, build its editor and run the integration
sequence with its production assets/bindings/timeline. No consumer repository
changes or final-video approval are claimed by this renderer handoff.
