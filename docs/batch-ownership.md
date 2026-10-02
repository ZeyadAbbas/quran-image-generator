# Batch ownership, reuse and practical limits

One request prepares all cues with a bounded 256-entry layout cache. Each process
call owns its native renderer/resources; independent calls may run concurrently
and always publish distinct `job-<random>` child directories. Cue IDs are metadata,
never filesystem names. Assets use deterministic content/style/runtime hashes.
Source/mapping, translation source/version/binding, profile revision, font/logo
bytes, canvas, effects and crop mode participate in identity. Persistent title/
logo keys exclude changing caption content. Every occurrence remains in order.

Optional `asset_cache_directory` reuses immutable, checksum-verified PNGs across
calls. Cache corruption fails explicitly; remove only the offending entry or
explicitly choose a fresh cache. Concurrent atomic publications are supported.
No credentials or provider calls are involved. Cache cleanup belongs to the
caller; exports pin all assets in their own job directory before publication.

Assets and manifest are staged, verified and atomically renamed into a unique
published directory. Failed/cancelled jobs remove only their own temporary files.
`all_or_nothing` publishes nothing on any required-layer failure; `per_cue` keeps
typed failures and publishes only assets referenced by successful cues. User
output roots and existing jobs are never overwritten. Required inputs are
rechecked before publication, and unreferenced partial PNGs are removed.

Limits: 8 MB request, 1,000 occurrences, 32 spans/cue, 16 layers, 8.5 million
canvas pixels, 32 MB local font/logo input, 512 unique PNGs and 512 MB output/job.
Effective fonts are at most 512 pixels. Native unbroken-line measurements larger
than 16,384 pixels fail before allocating a giant raster. Wand metric caches are
bounded to 512 entries. Split longer plans into jobs; work scales with unique
visual states and occurrence records, never frames. Caller metadata is not timing
analysis. Native resources close after each image; cache lifetime is explicit.

`execute_request(..., progress=callback, cancelled=predicate,
deadline_seconds=300)` checks cancellation/deadline between cues and layers.
The JSON request also supports `deadline_seconds` up to 3,600. CLI `--progress`
emits progress JSON lines to stderr, `--deadline` overrides the request budget,
and Ctrl+C produces a cancelled JSON result. An in-progress native draw finishes
before the next checkpoint; callers needing a hard stop should own the subprocess.

Run `python scripts/benchmark_captions.py --output /absolute/empty/benchmark-dir`
for authored 1/10-minute plans with 15/150 four-second occurrences, three Arabic
states and independently shared titles. It records cold/warm elapsed times,
asset counts and native-inclusive process peak RSS. Use an empty directory for
an actual cold run. These are throughput fixtures, not approved video timings.

Local Windows measurement on 2026-10-02 (Pillow 11.3.0, native ImageMagick
7.1.2-0 Q16 HDRI/RAQM, 576×1024): 15 occurrences produced seven shared assets
in 0.938 s cold / 0.354 s warm; 150 occurrences produced the same seven assets
in 0.869 s cold / 0.449 s warm. Process peak working set was 107–109 MiB,
including native allocations. The shorter case also includes initial startup
warming. Unique states, resolution and font/effect complexity drive cost; these
numbers are a budget example, not a guarantee for all 1/10-minute videos.
