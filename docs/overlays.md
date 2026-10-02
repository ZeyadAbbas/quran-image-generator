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
