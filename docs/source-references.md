# Source references, mapping revision simple-uthmani-1

The public `CorpusIdentity`, `SourceSpan` and `resolve_span` surface uses the
QuranScribe Tanzil Simple Hafs 1.1 hash, inclusive 1-based words after its
non-word filtering. Unnumbered basmala is 0:0, distinct from 1:1 and 27:30.
Chapter 9 never receives an opening basmala. Output always slices the verified
Uthmani file verbatim, with Python Unicode character offsets, half-open ranges.
Combining marks and following pause signs attach to the preceding word.

The checked-in bridge is built offline with exact normalized token anchors.
Normalization is solely evidence for mapping, never output text. Joined groups
must be selected together; internal boundaries fail with `mapping_boundary`.
Non-equal orthography groups are explicitly listed under `review` in the bridge
and cannot be selected partially. A full ayah is identified by its authoritative
surah/ayah identity even when internal spelling boundaries need review.
This conservative first revision deliberately does not guess those boundaries.

`bridge_data()['review']` is the exhaustive review backlog. A later reviewed
revision may admit more boundaries, with a new pinned mapping checksum. Runtime
rendering does not normalize, fuzzily align, or transfer whitespace ordinals.
The builder accepts only the recorded Simple hash; it needs the unchanged
creator-owned/source Tanzil Simple file as input. Rebuild with:

```
python scripts/build_word_bridge.py quran-simple.txt src/quran_image_generator/assets/data/quran-uthmani-1.1.txt src/quran_image_generator/assets/data/simple-uthmani-bridge.json
```

Update `BRIDGE_SHA256` to the generated payload digest after review. The table
contains derived offsets, not modified Quran text. Existing Tanzil notices apply.
