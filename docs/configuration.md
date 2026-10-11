# Configuration reference

Quran Image Generator reads YAML from `config.yaml` by default. Select another
file with `--config PATH` or through **Load config…** in the desktop app. The
GUI's **Save config…** writes the same public fields shown here. Runtime catalog
data is not written into configuration.

[`../config.yaml`](../config.yaml) is a complete working example. Its values are
chosen for that example and are not necessarily the defaults below.

## Loading and paths

- Missing or blank values use the defaults. Explicit invalid values are
  reported together instead of being silently ignored.
- Unknown keys are errors. Instagram credentials and publish actions belong in
  the environment and command line, not YAML.
- Relative output, background, and font paths are resolved beside the selected
  YAML file. Bundled font paths are also found in an installed package.
- A relative CLI `--output-dir` is resolved from the current working directory
  and overrides `output path` for that run.
- The GUI does not auto-save to `output path`: **Save PNG** always opens a save
  dialog and uses the configured path as its suggested initial directory.
- Quote colors so a leading `#` is not parsed as a YAML comment.

## Settings

| YAML key | Default | Accepted value and effect |
| --- | --- | --- |
| `output path` | `outputs` | Output directory; relative to the config file. |
| `resolution` | `1080 x 1080` | Positive `WIDTH x HEIGHT`, or `bg` to use a background image's dimensions. |
| `background image` | `blank` | Existing image path, or blank for a solid background. |
| `background color` | `000000` | Six-digit hex canvas color. |
| `quran font` | `Arial` | `Arial` or an existing `.ttf`/`.otf` path. |
| `quran color` | `FFFFFF` | Six-digit hex Arabic-text color. |
| `quran font size` | `34` | Positive whole-number pixel size. |
| `quran x position` | `30` | `center` or a non-negative offset measured from the right. |
| `quran maximum width` | `700` | Positive whole-number line width. |
| `quran line spacing` | `30` | Non-negative spacing between wrapped Arabic lines. |
| `quran word spacing` | `6` | Non-negative extra spacing between Arabic words. |
| `quran letter spacing` | `-0.1` | Any finite decimal. |
| `quran and translation spacing` | `30` | Non-negative gap between Arabic and translations. |
| `translation languages` | `blank` | Ordered list of up to three QuranEnc selectors; `[]` disables translations. |
| `translation color` | `FFFFFF` | Six-digit hex translation color. |
| `translation font size` | `16` | Positive default pixel size; an entry may override it. |
| `translation x position` | `40` | `center` or a non-negative offset measured from the left. |
| `translation maximum width` | `650` | Positive whole-number line width. |
| `translation language spacing` | `10` | Non-negative gap between different translations. |
| `translation line spacing` | `10` | Non-negative gap between wrapped lines. |
| `translation word spacing` | `1` | Non-negative extra spacing between translation words. |
| `translation letter spacing` | `0.0` | Any finite decimal. |
| `show verse numbers` | `false` | YAML boolean controlling verse-number medallions. |
| `verse number resolution` | `55 x 55` | Positive `WIDTH x HEIGHT`. |
| `verse number x offset` | `10` | Whole number from `-20` through `500`. |
| `verse number y offset` | `-20` | Any whole-number vertical adjustment. |
| `space between verses` | `70` | Whole number from `-10` through `200`. |
| `generate random verses` | `false` | With no CLI selector, choose a short random passage each iteration. |
| `total y offset` | `-10` | Any whole-number adjustment for the content block. |

The canvas and maximum widths are validated independently. A valid value can
still produce cramped content, so use the GUI preview to tune the selected
passage and translations.

## Translations

Arabic content always comes from the bundled Tanzil data. Optional translations
come from the current QuranEnc catalog and require network access. Inspect it
before choosing translations:

```sh
quran-image-generator --list-translations
```

Use an exact key whenever possible:

```yaml
'translation languages':
  - key: english_saheeh
    font size: 18
  - key: french_montada
    font: Arial
```

Each entry must contain exactly one of `key` or `language`. It may also set
`font` and `font size`; otherwise the global size and an appropriate bundled
language font, when available, are used. Order is preserved and duplicates are
rejected.

A language shortcut is intentionally strict:

```yaml
'translation languages':
  - language: en
```

It succeeds only if the catalog has exactly one resource for that language.
When there are several, choose one of the reported keys. The application stops
rather than silently changing translator or omitting requested content.

## Resolution and backgrounds

`resolution: bg` reads the dimensions of `background image`; it is an error if
the image is blank, missing, or unreadable. With an explicit resolution, the
background is composited at native size from the canvas's top-left corner:
larger images are cropped and smaller images can leave the solid background
color visible.

## Secrets and runtime choices

Quran content requires no account, key, or secret. These values are deliberately
not YAML settings:

- `QIG_INSTAGRAM_USERNAME` and `QIG_INSTAGRAM_PASSWORD` configure optional
  publishing.
- `--publish post` and `--publish story` are explicit per-run actions.
- Passage selectors, `--open`/`--no-open`, and `--output-dir` are runtime CLI
  choices.

Do not place Instagram credentials in YAML, screenshots, diagnostics, issues,
or commits. See [`troubleshooting.md`](troubleshooting.md) for common failures.
