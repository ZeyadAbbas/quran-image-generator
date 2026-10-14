# Word emphasis font fixtures

These unmodified fonts exercise full-line shaping and fill ownership. They are
test inputs, not new runtime defaults or automatic fallback fonts. All are
licensed under SIL Open Font License 1.1; the complete publisher notices and
licenses are adjacent to the font files.

Pinned upstream: [google/fonts at 66928797f271fed5ee428544e7229685e2d90127](https://github.com/google/fonts/tree/66928797f271fed5ee428544e7229685e2d90127).

| Local file | Upstream path | SHA-256 |
| --- | --- | --- |
| ScheherazadeNew-Regular.ttf | ofl/scheherazadenew/ScheherazadeNew-Regular.ttf | `794bac8dc9e83d1d620bc471ea694f5f31d0965ce8006490a79dfc51a2d283b3` |
| NotoNaskhArabic.ttf | ofl/notonaskharabic/NotoNaskhArabic[wght].ttf | `67b5a525a661b607971fbd3f96a81b89d3a768e74534fca84f18ac97e6fab72f` |

Noto's fixture includes its weight axis. The collection-face test creates a
temporary TTC from that fixture and the existing bundled Latin font. A fallback
test removes coverage from a temporary copy of the existing Madina font and
selects the unmodified Scheherazade fixture explicitly.

Issues #94/#95 use the actual DigitalKhatt Madina, Scheherazade New fallback, and
Amiri quotation/marker selectors from the consumer's `scribe-signature` preset.
[`../word-emphasis-signature.json`](../word-emphasis-signature.json) pins the
relevant settings from `quranscribe-cloud` revision
`e3504b12c3d60cbdb873f706b09989f74d3785ed`; the same Arabic style was verified at
#95's `fb9d9ce6dc37c33138a872a93c6b6bde4651b82a`. Tests add the reported 0.2
word spacing explicitly. No installed preset or downloaded font is needed.

| Local file | Pinned upstream | SHA-256 |
| --- | --- | --- |
| DigitalKhattMadina.otf | [DigitalKhatt/madinafont, 9aeb02c26d8dae4c032820733466c1ee9137e6d6/madina.otf](https://github.com/DigitalKhatt/madinafont/blob/9aeb02c26d8dae4c032820733466c1ee9137e6d6/madina.otf) | `b739d35562ea8bd28367a0cb069f993f025e6d7c8b6882eae01456fd82c0e9ef` |
| Amiri-Regular.ttf | [google/fonts, bd8f81ddb5c74d5c8897b36ad88b440266245103/ofl/amiri/Amiri-Regular.ttf](https://github.com/google/fonts/blob/bd8f81ddb5c74d5c8897b36ad88b440266245103/ofl/amiri/Amiri-Regular.ttf) | `ab391c4147d054c48976e98322ad0eefe1427aa0e0502a12a4c75d80a70cfcd7` |

DigitalKhatt retains its original CFF variable font axes. The tests use the
original bytes and fonts' full licenses are adjacent; temporary synthetic GSUB
fixtures exercise real inseparable word/decoration ligatures separately.
