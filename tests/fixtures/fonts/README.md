# Word emphasis font fixtures

These unmodified fonts exercise full-line shaping and fill ownership. They are
test inputs, not new runtime defaults or automatic fallback fonts. Both are
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
