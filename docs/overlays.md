# Transparent overlays

`render_overlay` draws a strict `ImageLayout` onto a real RGBA PNG. It uses
straight (unassociated) alpha and sRGB color channels; composite with normal
source-over in the consumer. Outside ink alpha is zero, antialiasing retains
fractional alpha, and a global layer opacity multiplies alpha. No color key or
background matte is applied. Opaque still-image behavior remains unchanged.

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

New scene text uses Pillow's RAQM/Harfbuzz path, or native ImageMagick RAQM on
Windows wheels without it, for bidi and Arabic shaping. It fails if both lack
shaping support. Existing Wand still
image rendering remains intact. Scene fields are public API features; the current
GUI edits the existing YAML still-image settings only.
