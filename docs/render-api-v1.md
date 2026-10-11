# Static caption API v1 (renderer 0.3.5)

Public imports: `quran_image_generator.api` (`RenderRequest`, `RenderResponse`,
`execute_request`, `capabilities`), `quran_image_generator.requests` (`Canvas`,
`CueRequest`, `BatchRequest`, `AssetSelector`, `TranslationSnapshot`), and the documented references, bindings, snapshots
and profiles modules. Private layout/content helpers are not consumer APIs.

Published UTF-8 JSON schemas ship in `assets/schemas`: `request-v1.json`,
`response-v1.json`, `bindings-v1.json`. Python and CLI use the same schema and
implementation. [Caption Studio](caption-studio.md) edits these same requests in
the desktop GUI, with native controls for every supported style field.
Unknown request fields/versions, duplicate occurrence IDs,
unsupported corpus hashes and oversized requests fail before image production.
Sources use inclusive 1-based words. Target Unicode character ranges and pixel
boxes are half-open. Pixel origin is upper left; x goes right, y goes down.
Layer anchors/regions are normalized 0..1; styles use 576-pixel reference units.

## Operations

- `capabilities` returns versions, exact corpus/mapping hashes, generic feature
  flags, supported layer roles/style fields, runtime
  shaping support, output conventions and limits. It needs no fonts/credentials.
- `preflight` verifies native libraries, shaping, corpus, fonts/glyphs, offline
  bindings and writable output. With cues it also checks the actual layouts.
- `validate` and `layout` resolve the same content and measure actual shaped fit,
  lines, glyph coverage, anchors and conservative effect boxes without writing
  images. `validate` includes layout validation; there is no acoustic analysis.
- `render_batch` produces a unique child job directory beneath `output_directory`.
  Every occurrence remains in the ordered cue list. Identical static states share
  assets. Caller metadata, including seconds, is echoed without interpretation.
- `translation_catalog` explicitly retrieves provider editions. Optional
  `translation_language="en"` filters English. It returns `translation_catalog`
  records with `resource_id`, name, description, version and language metadata.
- `prepare_translations` explicitly downloads a selected edition before rendering,
  or reads a checksum-pinned source offline. See the request below. Complete ayah
  spans receive verbatim **unreviewed** bindings; partial spans remain unbound
  (`needs_phrase_review`). Repeated occurrences retain their IDs and share exact
  bindings. No words, timing, typography or consumer settings are inferred.

`cues[].spans` is mandatory; `translation_policy` defaults to `none`. `required`
needs an approved exact binding in `translation_dataset` or an immutable
`translation_snapshot` (directory + hash). `review` permits an explicitly marked
Arabic-only preview if English is missing/unapproved. Underlying source/version,
Arabic hashes and binding revision are pinned; translation is never downloaded
during export. Use explicit prepare/import APIs first.

For an explicit draft, `review` plus `preview_unreviewed_translation=true` shows
an existing unapproved exact binding with review warnings. Without that flag,
the previous Arabic-only behavior remains. This never approves the wording;
`required` still rejects unapproved bindings.

```json
{
  "schema_version": 1,
  "request_id": "english-source",
  "operation": "prepare_translations",
  "source_corpus": {"name": "tanzil", "version": "1.1", "script": "simple", "sha256": "<capabilities hash>"},
  "translation_resource": "<resource_id from translation_catalog>",
  "snapshot_directory": "/absolute/source-cache",
  "source_license": "<source terms supplied by caller>",
  "source_attribution": "<edition and provider attribution>",
  "cues": [{"cue_id": "first-pass", "spans": [{"surah": 112, "ayah": 1, "word_start": 1, "word_end": 4}]}]
}
```

Use the full corpus identity returned by capabilities. The response contains
`translation_preparation.dataset`, ordered `.cues`, and `.source_snapshot`
(absolute directory + SHA-256). Save the dataset for rendering. A later request
with `source_snapshot_sha256` reuses those exact bytes without contacting the
provider, checking the selected resource, corpus and source notices first.
`translation_unavailable` is retryable; invalid editions and corrupt/stale pins
fail explicitly. Network access is confined to these two preparation operations.

`profile` is complete structured configuration (ID/revision/approval/styles/
provenance); `plain/1` defaults to undecorated white text. Profile names are caller
metadata, never switches selecting an installed creator or QuranScribe preset.
Every custom style is supplied in the request. `assets` maps layer roles to a local path, SHA-256,
license and attribution; absent fonts use identified bundled fallbacks. Logo is
absent unless explicitly supplied. `titles`, `quotations`, `verse_numbers` and
`cropped` default to false. Separate basmala with titles needs `title_surah`.
Title cues crossing chapters must be split, rather than assigning a wrong title.
`require_approved_profile` rejects unapproved profile exports when enabled.

## Response and failure semantics

Each cue contains exact verified Arabic, resolved source ranges, original/edited
translation and provenance/review state, caller metadata, line/layout plans,
asset IDs, warnings and a typed error on failure. Assets include job-relative
paths, actual PNG checksums/dimensions, straight alpha/sRGB, placement offsets,
actual ink boxes, conservative effect boxes, anchor, role and persistent state.
Titles/logo share stable asset references and update with actual chapter changes.
Profile/runtime/corpus/mapping versions and source attribution accompany results.
The copyable `examples/captions/render-response.json` documents a complete
response, with installed font paths and the caller-owned job root replaced by
portable placeholders. Use actual returned paths when consuming a live result.

Top-level `complete` means all requested cues are ready; `needs_review` contains
preview assets requiring content/profile review. `partial` is possible only with
explicit `error_mode=per_cue`; failed cue records remain visible. Default
`all_or_nothing` writes no assets when any cue fails validation. Published jobs
contain a manifest; temporary jobs are removed on failures. Callers own published
files and cleanup, and must use status plus checksum verification before export.
Required fonts/glyphs/layers never disappear silently. Disabled/empty optional
layers have explicit layer status. The headless adapter never opens the GUI or
publishes; Caption Studio is an optional desktop caller of the same contract.

Stable errors include `unsupported_version`, `invalid_request`, `duplicate_cue_id`,
`unsupported_corpus`, `invalid_reference`, `mapping_boundary`, `missing_asset`,
`changed_asset`, `missing_font`, `missing_glyph`, `missing_shaping`,
`layout_overflow` (with diagnostic boxes/suggestions), `missing_translation`,
`translation_review`, `stale_translation`, `offline_translation_miss`,
`corrupt_snapshot`, `profile_review`, `cancelled`, `output_io`, `render_failed`.
The error record includes retryability; repairing input differs from retrying I/O.

## Machine invocation

```
quran-caption-render --capabilities
quran-caption-render --request "caption plan.json"
quran-caption-render --request - --asset-root "/absolute/job inputs"
python -m quran_image_generator.machine_cli --request "caption plan.json"
```

The file adapter roots relative paths beside the request file; stdin uses explicit
`--asset-root` (otherwise the current directory). Absolute paths work everywhere.
Stdout is exactly one UTF-8 JSON response; human logs belong to stderr. Exit 0
means complete/review preview; exit 2 means failed/partial. No prompt, browser,
viewer, Tk window or publisher is opened. Consumer timing/fades/video encoding
remain outside this API. See installed handoff examples in the integration guide.
