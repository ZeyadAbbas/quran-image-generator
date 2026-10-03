# Source references, canonical word index simple-uthmani-5

The public `CorpusIdentity`, `SourceSpan` and `resolve_span` surface uses the
QuranScribe Tanzil Simple Hafs 1.1 hash, inclusive 1-based words after its
non-word filtering. Unnumbered basmala is 0:0, distinct from 1:1 and 27:30.
Chapter 9 never receives an opening basmala. Output always slices the verified
Uthmani file verbatim, with Python Unicode character offsets, half-open ranges.
Combining marks and following pause signs attach to the preceding word.

The checked-in index resolves canonical verse/word references to character
positions in the display corpus. Rendering never compares ASR spelling or
requires a second spelling approval. Revision 5 removes the orthography gate:
equal-sized word runs are indexed by position, including formerly grouped runs
whose spellings differed. Small connecting letters, dagger alif and hamza forms
remain verbatim display text and do not invalidate Quran word identities.

Joined groups must still be selected together; an internal boundary fails with
`mapping_boundary` because it splits one display word. The error refers only to
word boundaries. Existing authored structural partitions are preserved, including
5:72's joined vocative and separate Israel word. Every previously selectable
slice stays unchanged. Revision 3 and 4 English bindings retain their exact span,
source provenance and Arabic hash checks.

`bridge_data()['review']` is empty; canonical words are not spelling-review work.
Runtime rendering only looks up positions and slices the checked Quran text.
The builder accepts only the recorded Simple hash; it needs the unchanged
creator-owned/source Tanzil Simple file as input. Rebuild with:

```
python scripts/build_word_bridge.py quran-simple.txt src/quran_image_generator/assets/data/quran-uthmani-1.1.txt src/quran_image_generator/assets/data/simple-uthmani-bridge.json
```

Update `BRIDGE_SHA256` to the generated payload digest. The table
contains derived offsets, not modified Quran text. Existing Tanzil notices apply.

## Phrase selection

`ExcerptRequest` and `select_excerpt(s)` preserve ordered spans and occurrence
IDs. No ASR text is accepted. Each resolved span reports `starts_ayah` and
`ends_ayah`. `verse_markers` identifies only true numbered endings, including
verse-tail selections; separate basmala has no numeric marker. Quotations are
visual decorations and are never added to `Excerpt.text`. Translation policy is
explicit (`none`, `review`, `required`); a required policy needs a phrase binding,
never a complete-ayah translation silently attached to partial Arabic.
