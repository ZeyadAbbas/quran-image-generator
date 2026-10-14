# Source references, canonical word index simple-uthmani-5

The public `CorpusIdentity`, `SourceSpan` and `resolve_span` surface uses the
QuranScribe Tanzil Simple Hafs 1.1 hash, inclusive 1-based words after its
non-word filtering. Unnumbered basmala is 0:0, distinct from 1:1 and 27:30.
Chapter 9 never receives an opening basmala. By default output slices the verified
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
Tanzil Simple file (now also bundled) as input. Rebuild with:

```
python scripts/build_word_bridge.py quran-simple.txt src/quran_image_generator/assets/data/quran-uthmani-1.1.txt src/quran_image_generator/assets/data/simple-uthmani-bridge.json
```

Update `BRIDGE_SHA256` to the generated payload digest. The table
contains derived offsets, not modified Quran text. Existing Tanzil notices apply.

## Verified Simple display

Renderer 0.6.0 accepts explicit `arabic_script="simple"` in schema-1 requests,
typed `BatchRequest`, `ExcerptRequest`, and `resolve_span(..., arabic_script="simple")`.
The default remains `"uthmani"`. Simple mode slices the newly bundled verbatim
Tanzil Simple Hafs 1.1 file, byte-pinned to `CorpusIdentity.sha256`, using the same
verified canonical word counts. Chapter-opening basmala is addressed separately;
there is no text normalization, guessed offset, external corpus override, or
silent expansion. For example, 2:267 words 1..1 returns exactly `يَا` in Simple,
while the default Uthmani mapping still reports `mapping_boundary`.

Capabilities/style descriptors expose `source_rendering.scripts`. Responses echo
`corpus.display_script`, display edition/version/hash, and the actual target and
mapping hashes. Simple resolved spans use `mapping_revision="simple-verbatim-1"`
and the Simple target SHA-256. Canonical `source_corpus` stays the same in both
scripts; it describes source word references, independently of display spelling.
Layout identities include the chosen display edition, even for identical text.

Phrase bindings must match the selected excerpt's exact Arabic hash. New Simple
bindings use `simple-verbatim-1`; existing Uthmani bindings remain valid for their
original text and can be reused only when the actual Arabic hash is identical.
Switching scripts never rewrites or approves a binding. `prepare_translations`
accepts the same script option, emits unreviewed whole-ayah bindings for that
display text, and leaves partial spans at `needs_phrase_review`.
Simple mode supports the same occurrence selectors, word states, source breaks,
fonts, ornaments, crop geometry, title/translation assets, and static backends.

## Phrase selection

`ExcerptRequest` and `select_excerpt(s)` preserve ordered spans and occurrence
IDs. No ASR text is accepted. Each resolved span reports `starts_ayah` and
`ends_ayah`. `verse_markers` identifies only true numbered endings, including
verse-tail selections; separate basmala has no numeric marker. Quotations are
visual decorations and are never added to `Excerpt.text`. Translation policy is
explicit (`none`, `review`, `required`); a required policy needs a phrase binding,
never a complete-ayah translation silently attached to partial Arabic.
