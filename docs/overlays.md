# Transparent overlays

`render_overlay` draws a strict `ImageLayout` onto a real RGBA PNG. It uses
straight (unassociated) alpha and sRGB color channels; composite with normal
source-over in the consumer. Outside ink alpha is zero, antialiasing retains
fractional alpha, and a global layer opacity multiplies alpha. No color key or
background matte is applied.

`cropped=True` removes unused canvas pixels, returns exact `(x,y)` placement and
full-canvas half-open bounds. A cropped asset placed at that offset reproduces
the full overlay. Blank layers remain transparent full-canvas assets with null
bounds. Required marker loading errors fail; disabled optional layers are omitted
by the scene contract with an explicit status. Timing/fades belong to the caller.

## Independent scene layers

`Scene`, `Layer`, `plan_scene`, `render_layer` and `caption_scene` provide separate
Arabic/Latin titles, Arabic excerpt, translation and local PNG/logo roles.
Every layer owns its normalized anchor/region, opacity, z-order, enabled/required
state and persistent flag. Title/logo asset identity is independent of caption
length. Images use contain sizing with their original aspect ratio and alpha.
No default creator logo is substituted. Arabic names come from bundled metadata.
Separate basmala defaults to title-off; the consumer decides its chapter context.

Scene text defaults to Pillow's RAQM/HarfBuzz path; `render_backend: "imagemagick"`
selects native RAQM explicitly. Missing shaping fails without changing libraries.
Both libraries also support still-image rendering; their metrics and pixels
can differ. See [rendering backends](rendering-backends.md).
[Caption Studio](caption-studio.md) provides GUI
controls for the public caption request's styles, assets, bindings and export
options. The still-image GUI retains its existing YAML settings.
