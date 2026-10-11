# Troubleshooting

Start with the complete error shown by the GUI status area or CLI.
Configuration validation reports all discovered field problems together; fix
those before troubleshooting rendering or network access. Never include
Instagram passwords, private images, or personal paths in a bug report.

## Arabic content cannot load

Arabic text and chapter metadata are installed with the package and need no
network connection. Reinstall the project if the app reports missing bundled
data or a failed integrity check:

```sh
python -m pip install --force-reinstall -e .
```

Do not edit the files under `assets/data`: the Tanzil text is intentionally
verified by SHA-256 and must remain verbatim.

## Translations are unavailable

Arabic-only generation remains available. Check network access and inspect a
fresh QuranEnc catalog:

```sh
quran-image-generator --list-translations --refresh-catalog
```

Use the exact reported `key`. A `language` selector succeeds only when one
current resource has that language. The application supports at most three
translations and preserves their configured order. Use
`translation languages: []` to verify an offline Arabic-only render.

An HTTP `429` response is rate limiting; wait before trying again. An HTTP `5xx`
response generally indicates a temporary upstream problem. The client retries
bounded transient failures and rejects malformed or incomplete content rather
than rendering partial translations.

## ImageMagick or Wand cannot start

The Python `Wand` package is only the binding; native ImageMagick libraries must
also be installed and discoverable. Follow the
[Wand installation guide](https://docs.wand-py.org/en/latest/guide/install.html)
and [ImageMagick downloads](https://imagemagick.org/script/download.php), then
restart the terminal or desktop app.

The GUI remains available for configuration and help when renderer setup fails,
but preview and generation stay disabled. Ensure ImageMagick and Python use the
same architecture, normally 64-bit.

## The GUI does not open

Check Tk and the display first:

```sh
python -m tkinter
quran-image-generator-gui --help
```

The first command should open a small test window. Some Linux distributions
package Tk separately, and remote sessions need a graphical display. The CLI
does not import Tk. The Docker image is CLI-only and has no GUI support.

## Text is missing, clipped, or poorly wrapped

- Confirm custom font paths exist and end in `.ttf` or `.otf`.
- Start with `assets/fonts/quran_font.ttf` for Arabic. A translation without a
  custom font uses a bundled language font when available, otherwise Arial.
- Reduce font sizes, increase the canvas or widths, adjust spacing, or select
  fewer verses/translations. Use the GUI preview after each change.
- `quran x position` is measured from the right; `translation x position` is
  measured from the left. Either accepts `center`.
- If `resolution: bg` fails, verify the background is readable or try an
  explicit `WIDTH x HEIGHT`.

## Configuration does not load or save

- Compare keys and ranges with [`configuration.md`](configuration.md).
- Quote hex colors, especially those beginning with `#` or `0`.
- Confirm the YAML directory is readable and its destination is writable.
- Config-relative paths move with the config file. A relative CLI
  `--output-dir` starts from the current working directory.

## A PNG is not where expected

In the GUI, **Save PNG** always opens a dialog. The config output path is only
the suggested directory; preview generation alone does not save a user output.

In the CLI, `--output-dir` overrides YAML. Filenames contain the chapter and
verse range, and generating the same passage can overwrite the prior PNG. Use
`--no-open` in containers, remote shells, and automation.

## Docker cannot read config or write output

- Mount the config at `/config/config.yaml` read-only and output at `/output`
  writable, matching the README.
- The runtime image uses non-root UID/GID `10001:10001`.
- Container YAML must use container paths. Mount custom backgrounds/fonts and
  reference their mount locations.
- Supply all three passage selectors or `--random`, plus `--no-open`.

## Instagram publishing fails

Install the optional extra with `python -m pip install -e ".[instagram]"`, then
set `QIG_INSTAGRAM_USERNAME` and `QIG_INSTAGRAM_PASSWORD`. Publishing is opt-in
and happens after saving, so keep the local PNG and retry separately. The
project cannot bypass account verification or throttling.

## Reporting a reproducible bug

Include the platform, Python version, ImageMagick version, command shape,
whether GUI or CLI was used, and the exact error. Use a minimal config without
private paths. If possible, reproduce with `translation languages: []` and
chapter 1 to separate rendering from translation-service problems.
