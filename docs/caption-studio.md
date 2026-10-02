# Caption Studio

Caption Studio is the general desktop editor for static caption layers. Every
user can select their own fonts, decorations, translations, titles, logo and
layout. It writes the same schema-1 requests consumed by the public Python and
JSON API. No QuranScribe preset is installed, and the ordinary still-image
editor and its YAML defaults remain available.

## Open the editor

In the main app choose **Caption Studio…**, or launch it directly:

```sh
quran-image-generator-gui --captions
quran-image-generator-gui --request "my caption request.json"
python -m quran_image_generator.gui_cli --captions
```

Tk needs a graphical Windows or Linux session. `--help` remains available without
Tk or a display. The renderer setup is the same as the
[installation guide](integration-install.md).

## Captions and passages

Select a chapter, verse and inclusive first/last source word. **Add range** appends
that range to the selected caption; **Replace range** replaces the selected range
(or the first range). **Whole verse** appends its complete source range. **Basmala**
appends the separate `0:0` four-word basmala. Remove the existing range if you want
only the appended one. Source Arabic comes from the verified corpus; it is not
editable. Ambiguous mappings report an error for review.

Ranges and captions retain their explicit order. **Duplicate** creates another
occurrence with the same spans and phrase binding, a unique ID, and copied
metadata. Reorder each list with its up/down buttons. Changing a range does not
silently retarget its old English binding: the renderer reports a stale binding.

Each caption has its own Arabic/Latin title overrides, optional basmala chapter
context, English policy (`none`, `review`, `required`), phrase-binding selection,
and optional start/end seconds. Seconds are metadata for a consumer; this program
does not time audio or make a video. **Caption timing / extra metadata…** edits any
additional metadata object, retaining fields supplied by another program.

## Layers and all style controls

Select Arabic caption, translation caption, Arabic title, Latin title or branding.
Every style field published by API v1 has a native control; these controls are
generated from the same field definitions. Switching layers preserves edits.
Use **Apply layer** to commit, **Import styles…** to load a reusable profile, or
**Save styles…** to share one independently of the caption request.

| Controls / request fields | Meaning |
| --- | --- |
| `font_size`, `min_font_size` | Initial and minimum readable sizes; initial size allows fractions. |
| `anchor`, `region` | Baseline x/y and left/top/right/bottom region, entered as comma-separated 0–1 fractions of the canvas. |
| `direction`, `alignment`, `baseline_anchor` | RTL/LTR shaping, left/center/right alignment, and first/last baseline placement. |
| `fit`, `max_lines`, `line_spacing`, `safe_margin` | Wrap or bounded shrink, line limit, interline spacing and required inset. Overflow fails with diagnostic boxes. |
| `horizontal_scale` | Horizontal scaling of the complete shaped line, preserving connected Arabic. |
| `color`, `opacity`, `enabled`, `required`, `z_order` | Fill color and alpha, visibility, required-layer behavior and compositing order. Color pickers are provided. |
| `outline_width`, `outline_color` | Outline thickness and color. |
| `shadow_offset`, `shadow_blur`, `shadow_color`, `shadow_opacity` | Horizontal/vertical offset, blur, color and alpha. |
| `quote_open`, `quote_close`, `quote_spacing`, `decoration_scale` | Opening/closing glyphs and ornament spacing/scaling; the source Quran text stays unchanged. |
| `numeral_system`, `marker_prefix`, `marker_suffix` | Latin or Arabic-Indic digits and optional glyphs surrounding the actual verse number. |
| `suffix_scale`, `suffix_spacing`, `suffix_offset` | Small end-number size, separation and vertical adjustment. Numbers appear only at true numbered verse endings. |
| `sha256` | Optional required font fingerprint; selecting an asset updates this pin. |

Sizes, outlines, offsets, spacing and margins use reference pixels at a
576-pixel-wide canvas and scale with canvas width. Normalized coordinates are
independent of resolution. Titles and branding are persistent layers; exported
asset IDs are reusable across captions with the same static appearance.
See [fit and safe regions](caption-fit.md) and [profiles](caption-profiles.md).

## Fonts, decoration fonts and branding

In **Fonts & Branding**, choose any of the five layer roles or the separate
quotation/number font. Browse to a local TTF/OTF font or, for branding, a PNG.
Record the license/terms and attribution, then choose **Use / pin this file**.
The selected file's SHA-256 is recorded and displayed. Branding can instead use
a font plus the explicit character in **Branding glyph**.

**Use bundled / omit logo** restores the bundled font for a text role, clears a
separate decoration font, or removes branding. Missing files, changed fingerprints
and unsupported glyphs fail visibly. An ordinary preview never refreshes a changed
file's fingerprint; explicitly pin it again after reviewing the replacement.
Fonts and logos are not embedded in exported request JSON, so recipients need
access to the selected files and their terms.

## Translations and review

**Import bindings…** loads a documented binding dataset. Alternatively enter the
provider, resource, version, translator, license, attribution and direction.
Select a binding ID and revision, enter its original source wording, then enter
the caption segments with one segment per line. The editor pins the exact ordered
Arabic spans, source text hash and translation identity hash.

If caption wording changes rather than simply reflowing the original source,
select **Caption wording is edited**. Enter a reviewer and select **Reviewed and
approved** only after review, then **Bind to selected caption**. Editing wording
or source details revokes approval. Required English must have an approved exact
binding; review policy permits an explicitly marked Arabic-only preview when
English is unavailable or unapproved. No automatic phrase translation is invented.

**Save bindings…** shares the dataset. **Pin snapshot…** writes and selects an
immutable offline snapshot. **Open snapshot…** verifies an existing pinned
snapshot; **Edit a local copy** creates an editable inline dataset without changing
that original snapshot. Export never downloads translations.

For source preparation, supply a QuranEnc key, chapters, license and attribution
and use **Download source…**. **Read verse source…** loads the corresponding full
verse wording and pinned version. It leaves caption segments empty for explicit
phrase authoring and review. Whole-verse source downloads are not phrase bindings.
See [translation bindings and offline snapshots](phrase-translations.md).

## Preview, export and request reuse

**Canvas & Export** controls width/height, output/cache folders, deadline, failure
handling (`all_or_nothing` or `per_cue`), request/style names, style revision/review
and provenance. Checkboxes enable titles, quotation ornaments, true verse-end
numbers, cropped layers and the requirement for approved styles. Styles are
generic caller data. Changing styles, canvas, decorations or assets resets style
review to `needs_review`; a user may explicitly approve the reviewed result.

- **Check setup** checks native shaping, corpus/mapping, asset fingerprints,
  glyphs, translations, output writability and the requested layouts.
- **Check fit** measures every caption and reports layer status, actual font size,
  line count and bounds without producing PNGs.
- **Preview** renders into a managed temporary job. Select a caption to see its
  exact exported assets composed in order with their recorded offsets.
- **Export layers** renders an immutable job folder containing individual
  transparent PNGs and `manifest.json`, with checksums, placement, source and
  review provenance. Progress and cancellation use the same batch API.
- **Save combined PNG…** saves the selected current caption at full resolution.
  Transparency is preserved. The checkerboard/dark/light/image preview background
  is included only when **Include preview background in combined PNG** is checked.
- **Save request…** saves every caption, all styles/assets, binding dataset or
  snapshot pin, output options and metadata as reusable schema-1 JSON.

Any edit disables PNG saving until a new preview/export succeeds. Results from an
older form revision are discarded. Requests are prompted for saving before an
unsaved editor is replaced or closed. Pages scroll on smaller displays.

Relative asset, output/cache and snapshot paths loaded from a request are resolved
beside that file and saved as absolute paths. Preview background choices are local
view settings, not renderer request fields. To share across machines, remap local
paths while retaining hashes. A GUI-produced request can be passed directly to
`quran-caption-render --request "my caption request.json"` or to `execute_request`.
No consumer-specific configuration name is necessary. For the supplied sample
videos, load the complete measured request from the
[QuranScribe handoff](quranscribe-handoff.md) and supply its actual local assets.
