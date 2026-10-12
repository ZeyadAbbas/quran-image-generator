# Caption typography (renderer 0.3.8, schema 1)

These opt-in controls do not change the Quran corpus, source hashes, phrase
bindings. All appear in effective-style inspection and native
Caption Studio controls and participate in immutable asset identities.

| Style | Units and behavior |
| --- | --- |
| `word_spacing` | Additional em per ordinary word separator, 0–2; resolved against the final fitted size. Zero retains the existing complete-line path. |
| `line_height` | Baseline-to-baseline em, 0–4. Zero retains ink height plus `line_spacing`; nonzero overrides it and reports overlapping ink/effect envelopes as `line_height_collision`. |
| `tracking` | Additional em between LTR Latin graphemes, 0–1. Combining marks stay with their base. Optional cross-grapheme kerning/ligatures are disabled. Connected scripts, unsupported symbols and leading combining marks fail with `unsupported_tracking`. |

Renderer 0.4.0 supports nonzero word spacing in both selected backends. Pillow
adjusts space-glyph advances in an in-memory font while shaping each complete
line; ImageMagick uses its native interword-spacing control. Measurement and
painting use the same font/advance. The layer's `typography.backend` reports the
selected library; see [backend setup and output differences](rendering-backends.md).
A tracked line is bounded to 512
graphemes. No artificial spaces are inserted into verified text.

A cue may add `line_breaks`, for example:

```json
[{"span_occurrence": 0, "source_word": 4, "mode": "forced"}]
```

Occurrence is zero-based in the cue's ordered spans; source word is the inclusive
canonical corpus index. `forced` always starts another line. `preferred` selects
the latest feasible hinted boundary only when wrapping is needed. An indivisible
source/display group, out-of-range occurrence, final empty break or duplicate
boundary fails as `invalid_break`. True ending markers stay before a break at
their span's end. Layout preserves the source and displays only whole words.

Caption Studio's **Source-word line breaks…** dialog numbers occurrences from 1
for people. Reordering ranges moves their hints; deleting/replacing a range
removes its old hints. Saving/reloading retains all policies. Translation segment
breaks continue to come from reviewed bindings.

Each layer's `typography` result includes final spacing in pixels, baseline step,
baselines, break character offsets and backend identity. Font-relative dimensions
are recomputed during shrink, and complete ink/effect bounds still control fit.
