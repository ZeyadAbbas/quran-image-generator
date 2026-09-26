# Troubleshooting

Start with the complete error shown by the GUI status area or CLI. Configuration
validation reports all discovered field problems together; fix those before
troubleshooting rendering or network access. Never include client secrets,
tokens, Instagram passwords, private images, or personal paths in a bug report.

## Credentials or Quran Foundation requests fail

- Confirm `QF_CLIENT_ID` and `QF_CLIENT_SECRET` are exported in the same process
  environment that starts the application. Local runs do not auto-load `.env`.
- Confirm `QF_ENV` is either `prelive` or `production` and matches the app that
  issued the credentials. Tokens are environment-specific.
- New apps start in pre-live. Its dataset currently contains only Al-Fatihah (1)
  and Al-Baqarah (2); other chapters require approved production access.
- Follow the official [quickstart](https://api-docs.quran.foundation/docs/quickstart/),
  [manual authentication guide](https://api-docs.quran.foundation/docs/quickstart/manual-authentication/),
  or [migration guide](https://api-docs.quran.foundation/docs/quickstart/migration/).
- `401 Unauthorized` usually means missing, invalid, expired, or
  environment-mismatched credentials. Recheck the exported values and `QF_ENV`.
- `403 Forbidden` means the app is authenticated but lacks access to that
  environment or resource; confirm approval and the permitted pre-live dataset.
- `429 Too Many Requests` is rate limiting. Stop rapid retries, wait, and reduce
  request frequency before trying again.
- `5xx` responses generally indicate a temporary upstream problem. Retry later
  after checking connectivity and service status. Content failures are reported
  rather than replaced with partial results.

Docker reads credentials only when `--env-file .env` (or individual `--env`
options) is passed. `.env.example` itself contains no credentials and is not
loaded automatically.

## A translation is unknown or ambiguous

Refresh and inspect the authenticated live catalog:

```sh
quran-image-generator --list-translations --refresh-catalog
```

Then use the exact reported `id` or `slug`. A `language` selector succeeds only
when one current resource has that language. The application supports at most
three translations and preserves their configured order. Use
`translation languages: []` to verify an Arabic-only render.

## ImageMagick or Wand cannot start

The Python `Wand` package is only the binding; native ImageMagick libraries must
also be installed and discoverable by the process. Follow the
[Wand installation guide](https://docs.wand-py.org/en/latest/guide/install.html)
and [ImageMagick downloads](https://imagemagick.org/script/download.php), then
restart the terminal or desktop app so updated library paths take effect.

The GUI remains available for configuration/help when renderer setup fails, but
preview and generation stay disabled until the native dependency is fixed. The
CLI also cannot render until it is fixed. Ensure the ImageMagick architecture
matches Python (normally both 64-bit).

## The GUI does not open

Check the Tk installation and display first:

```sh
python -m tkinter
quran-image-generator-gui --help
```

The first command should open a small Tk test window. Some Linux distributions
package Tk separately (often as `python3-tk`), and remote/headless sessions need
a working graphical display. See the [Python Tk documentation](https://docs.python.org/3/library/tkinter.html).
The CLI does not import Tk, so use a one-shot command with `--no-open` on a
headless machine. The Docker image is CLI-only and does not contain GUI support.

## Text is missing, clipped, or poorly wrapped

- Confirm custom font paths exist and end in `.ttf` or `.otf`. Relative paths
  are resolved beside the selected config file.
- Start with the bundled `assets/fonts/quran_font.ttf` for Arabic text. A
  translation entry without a custom font uses a bundled language font when
  available, otherwise Arial.
- Reduce font sizes, increase the canvas or maximum widths, adjust line spacing,
  or select fewer verses/translations. Use the GUI preview after each change.
- `quran x position` is measured from the right; `translation x position` is
  measured from the left. Either accepts `center`.
- If `resolution: bg` fails, verify `background image` points to a readable
  supported image. Try an explicit `WIDTH x HEIGHT` to isolate the problem.

## Configuration does not load or save

- Compare keys and value ranges with
  [`configuration.md`](configuration.md). Unknown keys and obsolete publishing
  keys are rejected; the error may suggest a close valid key.
- Quote hex colors, especially those beginning with `#` or `0`.
- Confirm the YAML's directory is readable and its destination is writable.
  Settings are validated before the output directory is created or a YAML save
  replaces an existing file.
- Config-relative paths move with the config file. A relative CLI
  `--output-dir` instead starts from the current working directory.

## A PNG is not where expected

In the GUI, **Save PNG** always opens a dialog. The config's output path is only
the suggested directory; preview generation alone does not save a user output.

In the CLI, `--output-dir` overrides the YAML. Filenames contain the chapter
name and verse range, and generating the same passage in the same directory can
overwrite the prior PNG. Check that the destination is writable. `--open` asks
the operating system to open the saved file; use `--no-open` in containers,
remote shells, and automation.

## Docker cannot read config or write output

- Mount the config file at `/config/config.yaml` read-only and the output
  directory at `/output` writable, matching the README examples.
- The runtime image uses non-root UID/GID `10001:10001`. On Linux, run with your
  host UID/GID as shown in the README or grant that container user write access.
- Paths in container YAML must be container paths, not host paths. Mount custom
  backgrounds/fonts read-only and reference their mount locations.
- Docker has no desktop GUI. Supply all three passage selectors or `--random`,
  plus `--no-open`, so the run is non-interactive.

## Instagram publishing fails

Install the optional extra from this checkout with
`python -m pip install -e ".[instagram]"`, then set
`QIG_INSTAGRAM_USERNAME` and `QIG_INSTAGRAM_PASSWORD`. The CLI may prompt only
when attached to a terminal; the GUI never prompts. Publishing is opt-in and
happens after saving, so keep the local PNG and retry separately. Instagram may
require verification or throttle automated logins; the project cannot bypass
account security controls.

## Reporting a reproducible bug

Include the platform, Python version, ImageMagick version, command shape (with
values redacted where needed), whether GUI or CLI was used, and the exact error.
Use a minimal config without secrets or personal paths. If possible, reproduce
with `translation languages: []` and a pre-live chapter 1 passage to separate
rendering from catalog-selection problems.
