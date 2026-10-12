# Translation tracks and reference labels (renderer 0.3.13, schema 1)

The legacy `translation_dataset`/`translation_snapshot`, cue
`translation_binding_id`, `assets.translation` and `profile.styles.translation`
keep their existing behavior. New `translation_tracks` are ordered independent
instances with semantic role `translation`. Their styles and fonts are local to
that instance; changing a legacy translation style does not change these tracks.

## Content and review

Each track has a stable `track_id` (1–64 characters, beginning with a letter;
letters, digits, `_`, `-`, `.` thereafter), optional descriptive BCP-47 `language`,
`enabled`, `translation_policy`, `preview_unreviewed_translation`, one `dataset`
or checksum-pinned `snapshot`, an optional default `binding`, `font`, `style`,
and `metadata`. IDs must be unique across tracks/annotations and cannot reuse
built-in role IDs. An edition is identified by its complete pinned source
provenance, not by its language or displayed text. Direction comes from that
source's `direction`; `style.font_language` controls shaping where supported.

A binding reference is **both** `binding_id` and `revision`. Cue `track_bindings`
maps track IDs to references, overriding only that cue's defaults. The renderer
verifies datasets once per batch, shares the canonical excerpt resolution per
cue, and independently checks each binding's exact ordered spans, Arabic hash,
corpus/mapping, source identity/content, revision and review state. There is no
translation download or lookup by approximate text/language during rendering.

| Per-track policy | Missing binding | Unapproved binding |
| --- | --- | --- |
| `required` (default) | Cue fails with exact track identity | Cue fails, even with draft consent |
| `review` | Track omitted; cue remains `needs_review` | Omitted unless `preview_unreviewed_translation=true`; cue remains `needs_review` |
| `none`, `enabled=false`, or `style.enabled=false` | No content/font/snapshot read | No approval changes; no layout slot |

Stale, mismatched, corrupt or wrong-revision bindings fail under both `review`
and `required`; they are never replaced with another edition. A track cannot
use `style.required=false` to evade binding review or fit checks: every visible
instance must fit. Choose explicit visibility/content policy to omit optional
content. Style
approval does not approve translation wording. Per-cue failures, atomic batches,
cancellation/deadlines and immutable output/cache behavior apply as before.

`font` is the usual `{path, sha256, license, attribution}` selector. No symbol
glyph, ambient font substitution or remote font is accepted. A track without a
selector uses the bundled default Latin font; choose an explicitly pinned font
covering the selected script. Whole-layer pinned fallback, face/axes, shaping
controls and panels use the normal [font](font-controls.md) and
[panel](caption-panels.md) contracts.

## Layout and returned identities

Active new instances require an explicit `caption_groups` flow group, or a
positioned group with `collision="reject"`. All new instances are also checked
against other ready foreground layers, including across groups. Effect/panel
overlap fails. Legacy-only requests retain their existing overlay behavior.
Flow group `layers` order controls visual order; `z_order` controls asset
composition order. Hidden/omitted tracks leave no empty slot.

```json
{
  "caption_groups": [{
    "group_id": "caption", "mode": "flow",
    "layers": ["arabic", "translation-en", "translation-ur", "source-label"],
    "region": [0.05, 0.1, 0.95, 0.9], "gap": 0.6, "fit": "shrink"
  }]
}
```

Each cue returns ordered `translation_tracks` with ID, language, policy,
ready/disabled/omitted/needs-review status, `displayed`, source and binding,
snapshot pin, font terms and metadata. Every plan has `layer.instance_id` and
its own `asset_id`; emitted instance assets include `instance_ids`. Records for
different editions remain separate even when their wording or PNG checksums
match. Cache keys include per-instance content/review provenance. Repeated
identical cues reuse assets. `inspect` reports per-instance effective styles,
origins, font coverage/terms and actual group geometry without writing PNGs.

Limits: 8 translation tracks, 4 annotations, 16 total scene/output layers
including titles, branding and shared panel layers; the request remains bounded
to 8 MB. Split larger jobs. See [group fit](caption-groups.md) for minima and
failure diagnostics. Errors include cue ID, track/layer ID and JSON Pointer to
the track field, cue binding override or group constraint.

## Presentation labels

`annotations` have unique `annotation_id`, `kind`, `enabled`, `font`, and `style`.
They are ordinary independent layers and must be included in the chosen layout.
They do not alter canonical Arabic or binding wording and are not verse-end
ornaments.

- `source_reference`: derived only from verified cue spans. `format` is `words`
  (default), `compact`, or `named`. All formats retain selection order/repeats,
  identify basmala separately, and disclose partial word ranges. Compact omits
  word ranges only for a complete ayah. Caller `text`/`track_id` is forbidden.
- `edition_label`: selects an exact `track_id`; default text is translator,
  resource and version. It is omitted when that track is not displayed. A
  custom `text` requires `approved=true`; pinned edition provenance is still
  returned separately.
- `annotation`: explicit bounded plain presentation `text`, requiring
  `approved=true`. Use `style.direction` and a covering font for its script.

Every label is at most 512 characters; longer derived labels fail explicitly.
Choose compact references or shorter approved edition text. Neither approved
metadata nor style data can provide an arbitrary Quran body or bypass bindings.

## Python, JSON and Caption Studio

`requests.TranslationTrack`, `TrackBindingRef`, and `Annotation` are typed
equivalents; pass them to `BatchRequest.translation_tracks`/`annotations` and
use `CueRequest.track_bindings` for exact per-cue revisions. The published
schema/discovery describes the same fields. The complete
[two-edition example](../examples/captions/translation-tracks.json) uses test-only
authored fixture wording; replace its datasets with reviewed production
bindings before use.

Caption Studio's **Translations and labels…** editor saves/loads these ordered
collections and the selected cue's binding overrides. Each instance has its
own style/font object; editing one does not alter another's review. Use
**Caption groups…** to specify joint flow, **Check fit**/**Preview** to validate
all enabled scripts, and **Save request…** for an exact round-trip. Preview and
export compose the same checksummed PNGs; crops retain exact offsets. The
instance editor currently exposes these advanced collections as schema-backed
JSON. QuranScribe owns its friendly selection/order/style UI and reviewed
production translation preparation.
