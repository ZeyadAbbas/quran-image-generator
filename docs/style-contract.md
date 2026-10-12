# Caption style contract, descriptor version 1

Schema-1 callers remain supported. `capabilities().style_contract` publishes the
complete style schema, defaults for each role, request schema and defaults,
asset roles, units, ranges, enums, semantic constraints and active backend.
The same style schema validates Python/JSON and generates Caption Studio controls.
It does not include product presets or consumer slider limits.

Use `inspect_request(request)` or JSON `operation: "inspect"` with ordinary
canvas, corpus and cues. It resolves assets and source content and runs the exact
layout planner without creating output files. Each cue's `inspection.layers`
reports effective fields, explicit/default origins, reference dimensions in
output pixels, fitted size and disabled/optional status. A failed fit remains a
failure; inspect does not silently remove an unusable field.

Reference dimensions default to canvas width / 576; `scale_basis` also supports
short-side and output-pixel units. Anchor x/y use normalized coordinates in the
canvas or declared region; baseline is the legacy default, with ink/block edge
modes available through [joint layout](caption-groups.md). `line_spacing` adds to
the largest line ink height. Ratios are dimensionless. Font sizes resolve to at
most 512 output pixels. Defaults include a minimum size of 12 reference pixels;
setting `font_size: 10` requires an explicit `min_font_size` no larger than 10.

Validation errors retain `invalid_request`/`invalid_profile` and provide a
`details.path` JSON Pointer plus up to 128 individual `diagnostics`, with stable
`invalid_field`/`unknown_field` codes, rejected values and constraints. Semantic
errors identify the resolved minimum, role and cue. Fit bounds and suggestions
remain available. Unknown fields fail instead of being dropped.

Pillow-RAQM and Wand-RAQM both implement the existing complete-line shaping
contract. Discovery reports backend support for each field, including the
[font-control](font-controls.md) and [spacing](caption-typography.md) limitations.
An unavailable backend/option fails before PNG output.

`instance_defaults` and index-adjusted z-order metadata describe independent
[translation and annotation instances](translation-tracks.md). Their own
styles/fonts do not inherit a legacy translation role's overrides. `inspect`
returns instance IDs and their resolved effective styles/origins/layout. The
[editor handoff](caption-style-roadmap.md) maps controls to renderer contracts
and QuranScribe responsibilities.
