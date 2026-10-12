# Ink anchors and joint caption flow (renderer 0.3.12, schema 1)

Legacy `anchor_mode: "baseline"` and `scale_basis: "width"` retain existing
geometry/pixels. Opt-in `ink_top`, `ink_middle`, `ink_bottom` anchors use shaped
glyph/decorative ink. `block_top`, `block_middle`, `block_bottom` use complete
effect/panel envelopes. `anchor_space` selects normalized `canvas` coordinates or
coordinates within the layer's caller region. `anchor_horizontal` is reading
`start`, `center` or `end`. Positions snap to output pixels, so no consumer ascent
or effect-padding arithmetic is required. Actual alpha edges agree within one
pixel across supported shaping paths.

Reference dimensions use `scale_basis`: `width` = canvas width/576 (legacy),
`short_side` = min(width,height)/576, `pixels` = fixed output pixels. This applies
to typography/effects/reference-unit panels. Em values always use final fitted
font size. Font inspection and effective-style inspection resolve the same basis.

An ordered shared group can position and fit text together:

```json
[{"group_id":"caption","mode":"flow","layers":["arabic","translation"],
  "region":[0.05,0.1,0.95,0.92],"vertical_alignment":"bottom",
  "horizontal_alignment":"center","gap":0.6,"unit":"em",
  "fit":"shrink","collision":"reject","panel":{"opacity":0.6}}]
```

Flow groups own child positions/available regions, retain complete wording,
enabled order, per-role fonts, minima, max lines and effects/panels. Missing or
disabled optional children leave no slot. `gap` and outer `padding` use the first
active text's fitted em or group reference pixels. A group's `scale_basis`
governs its reference dimensions. Text, font-glyph branding and annotation layers
can flow; PNG images remain supported in overlay groups.

`fit: "wrap"` keeps preferred sizes and wraps; `"shrink"` coordinates bounded
size reduction, preserving preferred ratios and optional per-child
`size_ratios` multipliers. It stops at the most restrictive role minimum.
Coordinated fitting is bounded to at most 257 attempts.
`"fail"` forbids automatic wrapping beyond supplied source/translation breaks.
Shared panel width/shadows are reserved before wrapping and the complete group
envelope determines edge alignment. One child cannot be positioned by two flow
groups; ungrouped titles/logos stay where their own profiles put them.

`mode: "overlay"` preserves independently specified positions. Ordinary scenes
allow intentional overlap. Only a declared `collision: "reject"` group checks
intersecting effect/panel envelopes. Region overflow, group minima and collisions
return structured child/group/cue identities, bounds, edge overflow and blocking
constraints. Layout batches return every failed cue without PNG output and retain
the existing cancellation/deadline/limits behavior.

`layout_info` reports preferred/effective sizes, shrink, baselines, glyph/effect/
block bounds, scaling, group factor/region/gap and position ownership. The
per-element geometry and crop offsets move together. Caption Studio exposes the
new anchor/scale choices and **Caption groups…**. User presets, safe-zone guides,
aspect variants and timing remain consumer choices.

`common_size_suggestion(layout_response)` returns per-instance reference sizes
from the smallest successful fitted size, plus every failed cue. A caller can
select a common-size policy and replay those sizes through layout; the helper
explicitly reports `requires_revalidation` rather than claiming a new layout has
already passed. Per-cue fitting remains the default.
