# Pinned font controls (renderer 0.3.9, schema 1)

Ordinary local font selectors retain their existing validation rules. Advanced
options are opt-in layer styles, available in Python, JSON and Caption Studio:

| Field | Contract |
| --- | --- |
| `font_face` | Zero-based collection face, 0–31. Ordinary fonts permit only 0. Collections are bounded to 32 faces. |
| `variation_axes` | JSON object of font axis tags and values. Tags/ranges come from inspection; unspecified axes use that font's defaults. |
| `font_features` | JSON array of OpenType tags, optionally `-tag`/`tag=0`. Unknown tags fail. Required Arabic joining, mark and ligature features cannot be disabled. Requires Pillow-RAQM. |
| `font_language` | Explicit BCP-47 shaping language. Requires Pillow-RAQM. |
| `font_fallbacks` | At most four ordered local font selectors with `path`, `sha256`, `license`, `attribution`, optional `font_face` and `variation_axes`. |

Fallback is deliberately **whole-layer**: the first candidate covering all of
the layer's content is selected before complete-line RAQM shaping. This keeps
mixed-direction context, connected words and combining marks in one face. A list
whose fonts only cover separate parts fails rather than fragmenting the caption.
This policy is advertised in capabilities. No OS lookup, downloads or synthetic
faces occur. An empty list preserves fail-on-missing-glyph behavior. Every
supplied fallback is pinned and rechecked, including unused entries.

Faces/axes are materialized with fontTools into deterministic, job-local scratch
font bytes, then used identically by measurement and painting on both shaping
backends. Scratch files are removed when the job ends. Manifests record source
and derived hashes, effective axes, feature/language choices and fallback use;
temporary filenames do not enter immutable asset identity. Caller-supplied font
terms remain attached. FontTools version is included in runtime identity.

`inspect_font(path, sha256=..., text=..., font_face=..., variation_axes=...,
font_size=30)` returns family/face names, collection faces, units/em, hhea
ascender/descender/line gap and pixel metrics, axis ranges/defaults/named instances,
available features and coverage/missing codepoints/words for the supplied sample.
The direct helper size is in output pixels. It pins bytes and creates no output
files. JSON `operation: "inspect_fonts"` accepts ordinary `assets` and optional
`font_samples` by role and reports the same metadata, resolving role defaults and
optional canvas width/576 scaling. Font metrics are font
metrics; actual glyph/effect envelopes still come from layout.

The complete caption `inspect`/layout results additionally identify every font
actually used. Missing coverage, wrong face, unknown/out-of-range axes, changed
bytes and unsupported backend choices have stable diagnostic codes and field
paths. Font features/language on ImageMagick fail explicitly; Pillow supports
these alongside word spacing in 0.4.0. Explicit font features cannot accompany grapheme
tracking, which deliberately disables cross-grapheme discretionary shaping.

For direct scene planning with advanced options, keep the prepared fonts alive:

```python
with FontWorkspace() as fonts:
    scene = fonts.prepare_scene(scene)
    plans = plan_scene(scene)
    render_layer(scene, plans[0], destination)
```

The public batch API manages this automatically. Caption Studio exposes structured
axis/features/fallback fields as JSON controls, retains them on save/reload, and
offers **Inspect font…** with actual Quran/available translation coverage.
