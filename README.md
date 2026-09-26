# Quran Image Generator

<p align="center">
  <img src="readme_images/logo.png" alt="Quran Image Generator logo" width="80" height="80">
</p>

Create customizable PNG images from Quran passages with a desktop app or a
command-line workflow. The revived application uses Quran Foundation's current
Content APIs, discovers translations from the live catalog, and keeps API and
publishing credentials out of configuration files.

> **Release status:** the project is usable from a source checkout and is under
> active development. There is no public PyPI package or published release yet.

## What it includes

- A desktop GUI for passage selection, complete layout editing, previewing,
  saving, and optional confirmed Instagram publishing.
- Interactive and one-shot CLI modes, including random passage generation and
  headless operation.
- Arabic text, up to three ordered live-catalog translations, bundled fonts,
  verse-number artwork, backgrounds, colors, spacing, and positioning controls.
- Validated YAML configuration, a non-root CLI Docker image, and offline tests
  and render smoke checks.

![Quran Image Generator desktop app showing Al-Fatihah 1:1 and its rendered preview](readme_images/gui.webp)

## Requirements

- Python 3.10 through 3.14. CI currently exercises the supported endpoints,
  Python 3.10 and 3.14.
- [ImageMagick](https://imagemagick.org/script/download.php) and its native
  libraries. See the [Wand installation guide](https://docs.wand-py.org/en/latest/guide/install.html).
- [Tk](https://docs.python.org/3/library/tkinter.html) and a graphical display
  for the desktop app. The CLI itself does not require Tk.
- Quran Foundation backend-app credentials for live catalog and passage data.

## Quick start: desktop app

Install ImageMagick, then clone this repository:

```sh
git clone https://github.com/ZeyadAbbas/quran-image-generator.git
cd quran-image-generator
```

Create an isolated [virtual environment](https://docs.python.org/3/library/venv.html)
from the repository root:

**Windows PowerShell**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

**Linux (POSIX shell)**

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Set credentials in the same terminal, then start the app:

```powershell
# PowerShell
$env:QF_CLIENT_ID = "your-client-id"
$env:QF_CLIENT_SECRET = "your-client-secret"
$env:QF_ENV = "prelive"
quran-image-generator-gui
```

```sh
# POSIX shell
export QF_CLIENT_ID='your-client-id'
export QF_CLIENT_SECRET='your-client-secret'
export QF_ENV='prelive'
quran-image-generator-gui
```

Use `quran-image-generator-gui --config path/to/config.yaml` to start with a
different configuration file. Choose a chapter and verse range, adjust the
layout, and select **Generate / Refresh**. **Save PNG…** always opens a save dialog;
the configured output directory is only its suggested starting location. Any
edit makes the current preview stale until it is regenerated. Publishing is
never implicit and requires confirmation in the app.

The GUI exposes the normal generation settings documented in
[`docs/configuration.md`](docs/configuration.md). It can load and save YAML,
open the most recently saved PNG, and display concise setup help. To verify Tk
and the current display independently, run `python -m tkinter`.

## Quran Foundation access

1. [Request access](https://api-docs.quran.foundation/request-access/) for a
   backend application.
2. Follow the official [quickstart](https://api-docs.quran.foundation/docs/quickstart/)
   and [manual authentication guide](https://api-docs.quran.foundation/docs/quickstart/manual-authentication/).
3. Export `QF_CLIENT_ID`, `QF_CLIENT_SECRET`, and optionally `QF_ENV` in the
   process environment. Never put secrets in `config.yaml`, screenshots, logs,
   issues, or commits.

`QF_ENV` accepts `prelive` (the default) or `production`. New applications begin
in pre-live, whose content dataset currently includes only Al-Fatihah (1) and
Al-Baqarah (2). Full-Quran access requires an approved production application.
Tokens are environment-specific. Existing integrations should also review the
[migration guide](https://api-docs.quran.foundation/docs/quickstart/migration/).
Endpoint details and current response fields are in the official
[Content API reference](https://api-docs.quran.foundation/docs/category/content-apis/).

`.env.example` is a template, not an application configuration loader. Local
source runs do **not** read `.env` automatically: export the variables or use
your own environment manager. Docker reads such a file only when you explicitly
pass `--env-file`.

## Command line

Run the CLI as either `quran-image-generator` or
`python -m quran_image_generator`.

```sh
# Repeating interactive prompts; generated images open by default
quran-image-generator

# One passage; one-shot modes do not open the image by default
quran-image-generator --chapter 1 --start 1 --end 7

# One random passage, then open it
quran-image-generator --random --open

# Explicit headless output location; this relative path is resolved from the CWD
quran-image-generator --chapter 2 --start 255 --end 255 --no-open --output-dir outputs

# Select a configuration file explicitly
quran-image-generator --config config.yaml --chapter 1 --start 1 --end 1
```

`--chapter`, `--start`, and `--end` must be supplied together. They cannot be
combined with `--random`. With no selector, the CLI repeatedly prompts for a
passage (or chooses random passages when `generate random verses` is enabled in
the config) and asks whether to continue. One-shot modes generate once and exit.
Use `--open` or `--no-open` to override each mode's default. On a server or in
automation, use a one-shot selector and `--no-open`.

Generated names are `<Chapter> <first> - <last>.png` (or
`<Chapter> <verse>.png`). Repeating the same passage in the same directory may
overwrite the earlier file. A config-relative output path is resolved beside
the selected config file; a relative `--output-dir` override is resolved from
the current working directory.

### Translation catalog

Translations are resolved from the live Quran Foundation catalog rather than a
bundled ID table:

```sh
quran-image-generator --list-translations
quran-image-generator --list-translations --refresh-catalog
```

List mode cannot be combined with passage selectors, `--random`, output/open
overrides, or publishing. A refresh replaces the in-process catalog only after
the new response succeeds.

Choose at most three resources in `config.yaml`; their order is preserved.
Prefer the catalog's exact `id` or `slug`. A `language` selector works only when
that language has exactly one live resource, otherwise the application reports
the exact choices. Use `translation languages: []` to disable translations.
See [configuration](docs/configuration.md#translations) for examples.

## Docker (CLI only)

The image runs as non-root user `10001:10001` and intentionally contains no GUI
or display stack. Build it from the repository root:

```sh
docker build --target runtime -t quran-image-generator .
```

On Linux, prepare the environment/output files and run:

```sh
cp .env.example .env                 # fill in credentials; do not commit it
mkdir -p outputs
docker run --rm \
  --user "$(id -u):$(id -g)" --env HOME=/tmp \
  --env-file .env \
  --mount type=bind,src="$(pwd)/config.yaml",dst=/config/config.yaml,readonly \
  --mount type=bind,src="$(pwd)/outputs",dst=/output \
  quran-image-generator \
  --config /config/config.yaml --output-dir /output --no-open \
  --chapter 1 --start 1 --end 1
```

The config mount is read-only and the output mount is writable. Mount any custom
background or font separately as read-only and reference its container path in
the YAML. Docker's `--env-file` behavior is separate from local source runs.
CI exercises this workflow with a Linux Docker engine. Docker Desktop's
Linux-container bind mounts on Windows are not covered by CI; use Docker's
[bind-mount guidance](https://docs.docker.com/engine/storage/bind-mounts/) with
absolute host paths rather than copying the POSIX command unchanged.

## Optional Instagram publishing

From this source checkout, install the optional extra:

```sh
python -m pip install -e ".[instagram]"
```

Set `QIG_INSTAGRAM_USERNAME` and `QIG_INSTAGRAM_PASSWORD`, then opt in per run
with `--publish post` or `--publish story`. A CLI attached to a terminal may
prompt for missing credentials (with a hidden password); the GUI never prompts
for them. Publishing is attempted only after the PNG is saved, and a publishing
failure does not remove the local file. Do not store credentials or publishing
choices in YAML.

## Configuration and help

- [`config.yaml`](config.yaml) is a working, annotated example rather than a
  statement of every default.
- [`docs/configuration.md`](docs/configuration.md) is the canonical setting
  reference, including defaults, ranges, paths, and translation selectors.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) covers credentials,
  ImageMagick, Tk, fonts, layout, Docker, and publishing failures.
- [`docs/gui-smoke-test.md`](docs/gui-smoke-test.md) is the manual GUI release
  smoke checklist.

## Development

Install from a checkout with the development extra, then run the offline checks:

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m mypy
python -m compileall -q -f src
python -m build
python scripts/verify_artifacts.py
```

CI runs the test and packaging matrix without live credentials. A real live-API
smoke test is separate and requires authorized Quran Foundation credentials.

## License and support

Released under the [MIT License](LICENSE.txt). Please use
[GitHub Issues](https://github.com/ZeyadAbbas/quran-image-generator/issues) for
reproducible bugs and focused feature requests, but redact credentials, tokens,
personal paths, and private generated content.

Quran text and translations are obtained from
[Quran Foundation](https://quran.foundation/). The bundled Arabic typeface comes
from [me_quran](https://tanzil.net/docs/me_quran_font), and multilingual fonts
come from [Google Noto Fonts](https://fonts.google.com/noto).
