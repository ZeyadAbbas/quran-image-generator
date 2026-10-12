# Caption panels and shared backplates (renderer 0.3.11, schema 1)

Optional `profile.styles.<role>.panel` adds a static backplate behind a text
layer. An empty object or `enabled: false` preserves legacy transparent pixels.
A nonempty object enables it and resolves these defaults:

| Field | Default and units |
| --- | --- |
| `mode` | `block`; also `line` or `region` for individual text layers |
| `color`, `opacity` | Black, 0.6; independent of text alpha |
| `padding` | `[0.5, 0.35]` horizontal/vertical |
| `unit` | `em` of final fitted font size, or `reference_pixels` scaled by width/576 |
| `corner_radius` | 0.25 in the chosen unit, clamped to half the shortest panel side |
| `border_width`, `border_color` | 0, black; border is drawn inside the rectangle |
| `shadow_offset`, `shadow_blur`, `shadow_color`, `shadow_opacity` | `[0,0]`, 0, black, 0; dimensions use the chosen unit |
| `inset` | `effects`; alternatively `ink`, controlling the envelope surrounded by padding |
| `region` | Optional normalized rectangle for `region` mode; otherwise the layer's allowed region |

Block panels surround all fitted lines/decorations; line panels follow each line.
Region panels fill the configured rectangle and require text to fit its padded
interior. Shrink recomputes em padding/effects and checks the complete panel plus
foreground envelope at each size. Overflow fails rather than clipping. Hidden
or missing text creates no panel. PNG logos do not accept this text-only option.
Text alpha is applied to foreground pixels, independently of panel alpha; opaque
glyph cores can appear over a 60%-opaque panel. Output is one combined RGBA asset
for each individually paneled text layer, with resolved rectangles/effect boxes
and cropped placement metadata in `panels`.

`caption_groups` can add one separately compositable shared backplate:

```json
[{"group_id":"caption","layers":["arabic","translation"],
  "panel":{"opacity":0.6,"padding":[0.5,0.35],"corner_radius":0.25}}]
```

Shared panels use `block` mode around the union of enabled, present member
envelopes. Missing/disabled optional roles contribute no space. Padding em uses
the first active text member's fitted size (30 reference pixels for image-only
groups). The panel is a separate `kind: "panel"`
layer, placed behind its children by z order. Each layout layer reports its
rendered `asset_id`; fontless panel assets report an empty `font_sha256`.
Panels plus text are bounded to 16 output layers and groups to 8. Group IDs are
unique (1–64 characters); unknown member IDs fail. Ordinary group `overlay` mode
does not reposition text. Rich group flow is a separate layout extension.

Caption Studio exposes per-layer panel JSON controls and **Caption groups…**.
Save/reload uses the public schema. Solid fill, border and panel shadow are
supported; gradients and moving-video background blur are not advertised.
