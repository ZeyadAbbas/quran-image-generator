"""Rebuild authored content fixtures; never infer or approve creator assets."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from quran_image_generator.bindings import (
    BindingDataset,
    PhraseBinding,
    TranslationSource,
    text_hash,
)
from quran_image_generator.excerpts import ExcerptRequest, select_excerpt
from quran_image_generator.profiles import creator_profile
from quran_image_generator.references import CorpusIdentity, SourceSpan, bridge_data
from quran_image_generator.scenes import caption_scene

# English is authored fixture text. It is not a verified translation edition or
# approval of the creator's words. Source IDs/hashes come from the local manifest.
CASES = [
    (
        "7339743928691821854",
        "1ef61916208cae13eb036d1761372774cb3b904d671ef86c51f9d19c51505656",
        [
            (31, 9, 1, 5, "staying there forever. Allah's promise is true."),
            (31, 9, 6, 8, "He is the Almighty, the Wise."),
            (
                31,
                10,
                1,
                27,
                "He created the heavens without pillars you can see, and placed firm mountains on earth.",
            ),
            (31, 11, 1, 3, "This is Allah's creation."),
            (31, 11, 1, 3, "This is Allah's creation."),
            (31, 11, 1, 14, "This is Allah's creation. Show what others have created."),
        ],
    ),
    (
        "7320492468246416670",
        "dbcb9cafd56a584ecd57b602fca737d9a936e7767fa74ee839b18be9b7a7b088",
        [
            (17, 13, 1, 6, "We have bound every human's destiny to their neck."),
            (17, 13, 1, 11, "A record will be brought out on the Day of Resurrection."),
            (17, 13, 7, 11, "A record will be brought out on the Day of Resurrection."),
            (17, 13, 7, 11, "A record will be brought out on the Day of Resurrection."),
            (17, 13, 7, 13, "A record will be brought out and found spread open."),
            (17, 14, 1, 7, "Read your record. You suffice as your own reckoner today."),
            (
                17,
                15,
                1,
                21,
                "Whoever is guided benefits themselves. No bearer carries another's burden.",
            ),
        ],
    ),
    (
        "7320203938483981599",
        "483c073bbc13d08d34935ea8aa71931a1c4d961cd2e4faf8fd1e438538c96487",
        [
            (2, 43, 5, 7, "and bow down with those who bow down."),
            (2, 44, 1, 5, "Do you urge people to righteousness and forget yourselves?"),
            (2, 44, 1, 5, "Do you urge people to righteousness and forget yourselves?"),
            (
                2,
                44,
                1,
                10,
                "Do you urge righteousness while forgetting yourselves, though you read the Scripture?",
            ),
            (2, 45, 1, 1, "Seek help."),
        ],
    ),
    (
        "7320147035552779550",
        "bc2db28e1bba1ccab481d355112176da8967ef06b90b3831dd03f68c893cdce6",
        [
            (5, 23, 1, 5, "Two God-fearing men"),
            (
                5,
                23,
                1,
                10,
                "Two God-fearing men blessed by Allah said to enter upon them.",
            ),
            (
                5,
                23,
                9,
                18,
                "Enter the gate upon them. When you enter, you will prevail. Trust in Allah.",
            ),
            (
                5,
                23,
                9,
                18,
                "Enter the gate upon them. When you enter, you will prevail. Trust in Allah.",
            ),
            (5, 23, 16, 21, "Trust in Allah if you are believers."),
        ],
    ),
    (
        "7320128271927020831",
        "4c7bc85f98567c1a9c78dbf4937b7b2296b2bbf303dcbb848f843947e11442d7",
        [
            (
                39,
                29,
                1,
                7,
                "Allah sets forth the parable of a slave owned by several quarrelsome masters,",
            ),
            (
                39,
                29,
                1,
                19,
                "Allah sets forth a parable of disputed ownership and one owner. Are they equal?",
            ),
            (39, 30, 1, 4, "You will die, and they will die."),
            (39, 30, 4, 4, "they will die."),
            (
                39,
                31,
                1,
                7,
                "Then you will dispute before your Lord on the Day of Resurrection.",
            ),
        ],
    ),
    (
        "7295439449779965214",
        "7d0a20ec6e9c940f4512b0c6ed66ddf1359be9d5a0d5e46ce9b62497068dbbd6",
        [
            (
                5,
                72,
                1,
                10,
                'Those who say, "Allah is the Messiah, son of Mary," have certainly fallen into disbelief.',
            ),
            (
                5,
                72,
                1,
                34,
                "The Messiah said to worship Allah, his Lord and your Lord.",
            ),
            (
                5,
                73,
                1,
                25,
                "There is only one God. Those persisting in disbelief face painful punishment.",
            ),
            (5, 73, 25, 25, "painful."),
        ],
    ),
]


def build(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    source = TranslationSource(
        "local",
        "authored-six-reference-fixtures",
        "1",
        "Fixture author",
        "CC0-1.0",
        "Authored test segments, NOT approved creator translations",
    )
    cases = []
    bindings = []
    for clip_id, digest, phrases in CASES:
        cues = []
        expected = []
        for index, (surah, ayah, start, end, english) in enumerate(phrases):
            span = SourceSpan(surah, ayah, start, end)
            assert end <= bridge_data()["verses"][f"{surah}:{ayah}"]["word_count"]
            cue_id = f"{clip_id}-{index}"
            excerpt = select_excerpt(ExcerptRequest(cue_id, (span,)))
            binding_id = f"{surah}:{ayah}:{start}-{end}"
            if not any(binding.binding_id == binding_id for binding in bindings):
                bindings.append(
                    PhraseBinding(
                        binding_id,
                        "1",
                        (span,),
                        text_hash(excerpt.text),
                        english,
                        text_hash(english),
                        (english,),
                        "approved",
                        "Authored regression fixture only",
                        source_identity_sha256=source.identity_sha256,
                    )
                )
            cues.append(
                {
                    "cue_id": cue_id,
                    "spans": [asdict(span)],
                    "translation_policy": "required",
                    "translation_binding_id": binding_id,
                }
            )
            expected.append(
                {
                    "arabic": excerpt.text,
                    "arabic_sha256": text_hash(excerpt.text),
                    "starts_ayah": excerpt.spans[0].starts_ayah,
                    "ends_ayah": excerpt.spans[0].ends_ayah,
                }
            )
        profile = creator_profile(
            caption_scene(excerpt, english=english, titles=True)
        ).to_dict()
        profile["styles"]["arabic"].update(fit="shrink", min_font_size=20, max_lines=4)
        cases.append(
            {
                "clip_id": clip_id,
                "source": f"https://www.tiktok.com/@islamstruebeauty/video/{clip_id}",
                "media_sha256": digest,
                "reference_seconds": 2,
                "approval": "needs_review",
                "expected": expected,
                "request": {
                    "schema_version": 1,
                    "request_id": clip_id,
                    "operation": "render_batch",
                    "source_corpus": asdict(CorpusIdentity()),
                    "canvas": {"width": 576, "height": 1024},
                    "profile": profile,
                    "titles": True,
                    "quotations": True,
                    "verse_numbers": True,
                    "cues": cues,
                    "output_directory": "rendered",
                },
            }
        )
    (root / "six-references.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "approval": "needs_review",
                "notes": "Authored content/geometry fixtures; original assets and translation edition unconfirmed. No timing approval.",
                "translation_dataset": BindingDataset(
                    source, CorpusIdentity(), tuple(bindings)
                ).to_dict(),
                "cases": cases,
            },
            ensure_ascii=False,
            indent=2,
        ),
        "utf-8",
    )


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "captions")
