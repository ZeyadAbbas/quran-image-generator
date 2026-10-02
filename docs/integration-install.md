# Independent QuranScribe handoff

Install renderer **0.2.x**, schema **1** in a separate environment. The intended
release tag is `v0.2.0`; a pinned merged commit or wheel is also supported. Until
that tag is available, pin the concrete merged API commit rather than floating
`main`. There is no claim of PyPI publication. Pick the executable/environment
explicitly, check `--capabilities`, and reject incompatible schema/renderer versions.

```
python -m venv renderer-env
# Activate renderer-env using the platform's normal venv activation.
python -m pip install "git+https://github.com/ZeyadAbbas/quran-image-generator.git@v0.2.0"
quran-caption-render --capabilities
quran-caption-render --preflight
quran-caption-render --request "/absolute/inputs/arabic-batch.json"
```

The built package requires Python 3.10–3.14. Linux needs ImageMagick native
libraries (`imagemagick`/`libmagickwand`), while a Pillow wheel supplies RAQM.
Windows needs the ImageMagick DLL build; set `MAGICK_HOME` to its actual installation
directory before starting the chosen renderer process. If Pillow lacks RAQM, the
native ImageMagick build must include it. Preflight reports the exact runtime,
verified corpus/mapping, font/glyph availability, pinned translation readiness
and output writability with actionable errors. It never asks for credentials.

`--preflight --request file.json` checks the actual requested cue/layout settings;
plain `--preflight` checks bundled/native readiness. A missing/changed creator
font or offline translation miss fails before video export. Export has no network
fallback. Scene JSON fields are API-only; the Tk GUI still edits still-image YAML.

Copyable fixtures under `examples/captions` cover Arabic-only/repeats, partial
ayahs, basmala, persistent titles, reviewed English imports, offline snapshots and
layout-only requests. Translation examples are explicitly authored test fixtures,
not identification/approval of the creator's translator. Use the creator's actual
reviewed dataset and source notice for production. Original fonts/logo paths and
licenses must be supplied; no substitute logo is claimed as approved.

`examples/caption_client.py` uses only installed public imports and negotiates
0.2.x/schema 1. It returns static assets; QuranScribe owns every occurrence's
timing/fades, chapter transitions, existing video frames/audio and final encoding.
No ASR, GUI or publisher is called. Independent CI invokes
`scripts/offline_caption_smoke.py` outside the checkout to compare public Python
and separate JSON-process assets with reviewed offline English and real alpha.

Each export owns one immutable `job-*` directory with a verified manifest and
relative PNG paths. Map `job_directory` to the consumer's host path, verify every
checksum, keep source/profile/translation review state, then composite straight
alpha/sRGB overlays. Cache/snapshot paths are explicit caller-owned locations.
Delete finished job directories only when no saved plan needs them. See API v1
and batch ownership docs for errors, progress, cancellation and deadlines.

For Docker, mount the request/assets/snapshot directory read-only at `/inputs`
and a writable output/cache directory at `/output`; invoke the machine adapter
with its request rooted at `/inputs`. Request paths refer to container locations.
Translate returned `/output/job-*` paths to the mounted host output directory.
Use the existing non-root UID mapping and native runtime image; no display stack
is needed. Preserve bundled Tanzil CC BY 3.0 and caller translation/font/logo
attribution with outputs. Creator visual approval and unresolved spelling-boundary
reviews remain explicit external data gates.
