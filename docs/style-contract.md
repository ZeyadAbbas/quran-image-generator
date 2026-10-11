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

Reference dimensions scale by canvas width / 576. Anchor x/y are normalized
canvas coordinates, with y at the first/last baseline. `line_spacing` adds to
the largest line ink height. Ratios are dimensionless. Font sizes resolve to at
most 512 output pixels. Defaults include a minimum size of 12 reference pixels;
setting `font_size: 10` requires an explicit `min_font_size` no larger than 10.

Validation errors retain `invalid_request`/`invalid_profile` and provide a
`details.path` JSON Pointer plus up to 128 individual `diagnostics`, with stable
`invalid_field`/`unknown_field` codes, rejected values and constraints. Semantic
errors identify the resolved minimum, role and cue. Fit bounds and suggestions
remain available. Unknown fields fail instead of being dropped.

Pillow-RAQM and Wand-RAQM both implement the existing complete-line shaping
contract. Discovery reports which backend is active; advanced features, variable
axes and fallback are explicitly unavailable until supported by that backend.
An unavailable shaping backend fails before PNG output.
