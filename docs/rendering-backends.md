# Rendering backends and preview performance

Renderer 0.4.0 defaults to Pillow. Source selection, verified Quran text,
translation approval, whole-word wrapping, shrink search order, groups, panels,
revision gating and exact-preview saves retain their existing rules. The
libraries have different text metrics and pixels, so the selected font sizes,
line breaks, antialiasing, resizing and output precision can differ.

## Selecting a backend

For still images, set the YAML field or use the Canvas tab:

```yaml
'render backend': pillow
```

Select `imagemagick` to retain the previous native still-image renderer, including
its 16-bit output where applicable. Caption requests use the top-level field:

```json
{"render_backend": "imagemagick"}
```

Omitting either field selects `pillow`. Caption Studio exposes the setting under
Canvas & Export and saves it in complete requests. Measurement and painting use
the same selected backend. Missing Arabic shaping produces an actionable error;
there is no silent change of rendering libraries or disconnected-letter fallback.

## Pillow setup

Pillow needs RAQM, HarfBuzz and FriBiDi for complex text. Linux/macOS Pillow wheels
normally provide these dependencies. On Windows, install a trusted standalone
64-bit `fribidi.dll`, `fribidi-0.dll` or `libfribidi-0.dll` beside the virtual
environment's executable (`.venv/Scripts`). Alternatively set
`PILLOW_FRIBIDI_DLL` to its absolute path **before starting Python**. The package
loads that library before Pillow initializes its shaping engine.

If ImageMagick is already installed, its FriBiDi DLL can provide the dependency
without installing another renderer. From the project directory, with your
actual ImageMagick installation path:

```powershell
Copy-Item -LiteralPath 'C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\CORE_RL_fribidi_.dll' -Destination '.venv\Scripts\fribidi.dll'
.venv\Scripts\python.exe -c "import quran_image_generator; from PIL import features; print(features.check_feature('raqm'))"
```

The check must print `True`. Native files are not downloaded or installed by the
renderer. See [Pillow's build documentation](https://pillow.readthedocs.io/en/stable/installation/building-from-source.html#external-libraries)
for platform dependencies. The ordinary Pillow PNG/JPEG/WebP pipeline works
without ImageMagick; optional SVG background decoding still requires it.

## Spacing and fonts

Pillow uses complete-line RAQM shaping for both measurement and painting. Extra
word spacing is applied to space-glyph advances in an in-memory font. Still-image
letter spacing adjusts nonzero glyph advances; zero-advance combining marks
remain zero, and connected Arabic is never split into individual characters.
Outlines, source font files, cmap and shaping tables remain intact. Spacing is
quantized to the font's units per em, so very small adjustments may round to zero.
Caption Latin grapheme tracking retains its existing independent behavior.

ImageMagick uses its original native spacing and rasterization. It continues to
reject explicit font-feature/language overrides, which require the Pillow path.
Font-file identities and all requested spacing/shaping options participate in
caches. Pinned input hashes, coverage and source/translation checks still run on
every caption request, including requests that restore cached layers.

## Caches

- Text geometry is cached independently of color and wrapping width. Actual text,
  font identity, size, spacing, direction, features and language remain in keys.
- Resized verse numbers and decoded backgrounds are reused until files change.
- Caption Studio keeps fitted plans and exact PNG bytes between requests. Cached
  plans bind to the current job's prepared fonts, including temporary faces/axes.
- ImageMagick measures native ink from a float pixel buffer, preserving bounds
  without cloning/trimming the raster. Its ordinary 8-bit caption masks transfer
  directly to Pillow; unusual higher-depth buffers retain the original decoder.
- Preview resizing reuses decoded images, caption compositions and backgrounds.
  Resize work is debounced; worker results are checked every 25 milliseconds.

Caches use bounded least-recently-used storage. Caption plan storage is bounded
to 128 entries/16 MiB, PNG storage to 256 entries/64 MiB, and each text-metric cache
to 8,192 entries/16 MiB. Cache hits never skip source, approval, input identity,
output checksum or stale-preview checks. Changing a backend invalidates its
layout/asset keys. Python API callers can opt into a reusable `CaptionRenderCache`
by passing `cache=` to `execute_request`; independent batch calls otherwise
retain isolated output jobs.

## Reproducing the measurements

Run each backend in a fresh process using the same configuration:

```sh
python scripts/benchmark_previews.py --config config.yaml --backend pillow --output /tmp/qig-pillow
python scripts/benchmark_previews.py --config config.yaml --backend imagemagick --output /tmp/qig-native
```

Local Windows measurements on 2026-10-12 (Python 3.12.10, Pillow 11.3.0,
ImageMagick 7.1.2-0 Q16 HDRI, bundled fonts, repository config) include layout and
PNG creation, but exclude imports, GUI polling/display and optional network calls.
These are individual runs, not latency guarantees:

| Case | Previous ImageMagick | Optimized ImageMagick | Pillow default |
| --- | ---: | ---: | ---: |
| Al-Fatiha, first render | 0.73 s | 0.65 s | 0.21 s |
| Al-Fatiha, color edit | 0.69 s | 0.19 s | 0.06 s |
| Ayat al-Kursi, first render | 1.30 s | 0.90 s | 0.11 s |
| Ayat al-Kursi, color edit | 1.48 s | 0.20 s | 0.07 s |
| Dense fitted caption, first render | 15.92 s | 5.80 s | 0.12 s |
| Dense fitted caption, repeated | — | 0.02 s | 0.02 s |

Eight pre-change native reference renders matched the optimized ImageMagick
pixels exactly: both passages at repository/GUI defaults, plus plain, titled,
dense and independent-decoration captions. Native still-image checks compare
full ImageMagick signatures and retain 16-bit depth. The regression suite also
compares float-buffer ink bounds with the original native draw/trim algorithm.
