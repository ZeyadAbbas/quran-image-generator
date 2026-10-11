# Caption typography (renderer 0.3.8, schema 1)

These opt-in controls do not change the Quran corpus, source hashes, phrase
bindings or legacy pixels. All appear in effective-style inspection and native
Caption Studio controls and participate in immutable asset identities.

| Style | Units and behavior |
| --- | --- |
| `word_spacing` | Additional em per ordinary word separator, 0–2; resolved against the final fitted size. Zero retains the existing complete-line path. |
| `line_height` | Baseline-to-baseline em, 0–4. Zero retains ink height plus `line_spacing`; nonzero overrides it and reports overlapping ink/effect envelopes as `line_height_collision`. |
| `tracking` | Additional em between LTR Latin graphemes, 0–1. Combining marks stay with their base. Optional cross-grapheme kerning/ligatures are disabled. Connected scripts, unsupported symbols and leading combining marks fail with `unsupported_tracking`. |

Nonzero word spacing uses complete-line native Wand-RAQM shaping and the font's
natural space advance, plus the requested additional em. Measurement and painting
use exactly the same advance. Discovery reports native support. A Pillow-only
installation receives `unsupported_shaping_option` before output; where native
RAQM exists, the selected layer's `typography.backend` explicitly reports Wand.
Other controls use either existing backend. A tracked line is bounded to 512
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
