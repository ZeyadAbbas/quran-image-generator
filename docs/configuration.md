# Configuration reference

Quran Image Generator reads YAML from `config.yaml` by default. Select another
file with `--config PATH` or through **Load config…** in the desktop app. The GUI's
**Save config…** writes the same public fields shown here; runtime catalog data and
credentials are never included.

[`../config.yaml`](../config.yaml) is a complete working example. Its values are
chosen for that example and are not necessarily the defaults in this reference.

## Loading and paths

- Missing or blank values use the defaults below. Explicit invalid values are
  reported together instead of being silently ignored.
- Unknown keys are errors. Legacy Instagram/publishing keys are also rejected;
  credentials and publish actions belong in the environment and command line.
- Relative `output path`, background, and font paths are resolved beside the
  selected YAML file. Bundled font paths such as
  `assets/fonts/quran_font.ttf` are also found in an installed package.
- A relative CLI `--output-dir` is different: it is resolved from the current
  working directory and overrides `output path` for that run.
- The validated output directory is created when settings are loaded for a run.
  The GUI does not auto-save there: **Save PNG** always opens a save dialog and
  uses it only as the suggested initial directory.
- Quote colors so a leading `#` is not parsed as a YAML comment and leading
  zeroes are preserved. Both `'#001122'` and `'001122'` are accepted.

## Settings

| YAML key | Default | Accepted value and effect |
| --- | --- | --- |
| `output path` | `outputs` | Output directory; relative to the config file. |
| `resolution` | `1080 x 1080` | Positive `WIDTH x HEIGHT`, or `bg` to use a valid background image's dimensions. |
| `background image` | `blank` | Existing image path, or blank for a solid background. |
| `background color` | `000000` | Six-digit hex canvas color. |
| `quran font` | `Arial` | `Arial` or an existing `.ttf`/`.otf` path. |
| `quran color` | `FFFFFF` | Six-digit hex Arabic-text color. |
| `quran font size` | `34` | Positive whole-number pixel size. |
| `quran x position` | `30` | `center` or a non-negative whole-number offset measured from the right. |
| `quran maximum width` | `700` | Positive whole-number line width; controls wrapping. |
| `quran line spacing` | `30` | Non-negative spacing between wrapped Arabic lines. |
| `quran word spacing` | `6` | Non-negative extra spacing between Arabic words. |
| `quran letter spacing` | `-0.1` | Any finite decimal; tightens or loosens glyph placement. |
| `quran and translation spacing` | `30` | Non-negative gap between the Arabic and translation blocks. |
| `translation languages` | `blank` | Ordered list of up to three catalog selectors; blank or `[]` disables translations. |
| `translation color` | `FFFFFF` | Six-digit hex translation color. |
| `translation font size` | `16` | Positive default pixel size; an entry may override it. |
| `translation x position` | `40` | `center` or a non-negative whole-number offset measured from the left. |
| `translation maximum width` | `650` | Positive whole-number line width; controls wrapping. |
| `translation language spacing` | `10` | Non-negative gap between different translations. |
| `translation line spacing` | `10` | Non-negative gap between wrapped lines of one translation. |
| `translation word spacing` | `1` | Non-negative extra spacing between translation words. |
| `translation letter spacing` | `0.0` | Any finite decimal. |
| `show verse numbers` | `false` | YAML boolean to show or hide verse-number medallions. |
| `verse number resolution` | `55 x 55` | Positive `WIDTH x HEIGHT`. |
| `verse number x offset` | `10` | Whole number from `-20` through `500`. |
| `verse number y offset` | `-20` | Any whole-number vertical adjustment. |
| `space between verses` | `70` | Whole number from `-10` through `200`. |
| `generate random verses` | `false` | YAML boolean; with no CLI selector, choose a short random passage for each interactive iteration. |
| `total y offset` | `-10` | Any whole-number adjustment for the complete content block. |

The canvas and maximum widths are validated independently. A width that is
valid YAML can still produce cramped or overflowing content, so use the GUI
preview to tune layout for the selected passage and translations.

## Translations

Run the authenticated catalog command before choosing translations:

```sh
quran-image-generator --list-translations
```

Use an exact live `id` or `slug` whenever possible:

```yaml
'translation languages':
  - id: 123  # example only: replace with an ID from the live list command
    font size: 18
  - slug: catalog-slug-from-the-list-command
    font: Arial
```

The `123` above is deliberately schematic, not a maintained catalog ID. Each
entry must contain exactly one of `id`, `slug`, or `language`. It may also
set `font` and `font size`; otherwise the global size and an appropriate bundled
language font (when available) are used. Order is preserved and duplicate
selectors are rejected.

A language shortcut is intentionally strict:

```yaml
'translation languages':
  - language: en
```

It succeeds only if the current live catalog has exactly one resource for that
language. When there are several, choose one of the reported IDs or slugs. The
application stops rather than silently using a different translator or omitting
a requested translation. Catalog availability and IDs can change upstream.

## Resolution and backgrounds

`resolution: bg` reads the dimensions of `background image`; it is an error if
the image is blank, missing, or unreadable. With an explicit resolution, the
background is composited at its native size from the canvas's top-left corner:
larger images are cropped and a smaller image can leave the configured solid
`background color` visible.

## Secrets and runtime choices

These values are deliberately not YAML settings:

- Quran Foundation credentials can be entered for the current GUI session with
  **API credentials…**, entered for one CLI run with `--prompt-credentials`, or
  supplied non-interactively through `QF_CLIENT_ID`, `QF_CLIENT_SECRET`, and
  `QF_ENV`.
- `QIG_INSTAGRAM_USERNAME` and `QIG_INSTAGRAM_PASSWORD` configure optional
  publishing.
- `--publish post` and `--publish story` are explicit per-run actions.
- Passage selectors, `--open`/`--no-open`, and `--output-dir` are runtime CLI
  choices.

Do not place credentials in YAML, screenshots, diagnostics, issues, or commits.
See the [README](../README.md#quran-foundation-access) for access setup and
[`troubleshooting.md`](troubleshooting.md) for common failures.
