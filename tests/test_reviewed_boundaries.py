import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_bindings import fixture_dataset

from quran_image_generator.references import ReferenceError, SourceSpan, resolve_span
from scripts.build_word_bridge import reviewed_groups


@pytest.mark.parametrize(
    "surah,ayah,ranges",
    [
        (17, 15, [(1, 10), (11, 13), (14, 15), (16, 21)]),
        (5, 72, [(1, 4), (5, 14), (15, 22), (23, 34)]),
    ],
)
def test_actual_consumer_phrase_boundaries_reconstruct_verbatim_ayah(surah, ayah, ranges):
    phrases = [resolve_span(SourceSpan(surah, ayah, a, b)) for a, b in ranges]
    full = resolve_span(SourceSpan(surah, ayah, 1, ranges[-1][1]))
    assert " ".join(p.text for p in phrases) == full.text
    assert phrases[0].starts_ayah and phrases[-1].ends_ayah
    assert all(not p.ends_ayah for p in phrases[:-1])
    assert all(not p.starts_ayah for p in phrases[1:])
    assert [p.character_end + 1 for p in phrases[:-1]] == [
        p.character_start for p in phrases[1:]
    ]


@pytest.mark.parametrize(
    "span,text",
    [
        (SourceSpan(17, 15, 5, 5), "لِنَفْسِهِۦ"),
        (SourceSpan(5, 72, 13, 14), "يَٰبَنِىٓ"),
        (SourceSpan(5, 72, 15, 15), "إِسْرَٰٓءِيلَ"),
        (SourceSpan(5, 72, 20, 20), "إِنَّهُۥ"),
        (SourceSpan(5, 72, 29, 29), "وَمَأْوَىٰهُ"),
    ],
)
def test_reviewed_spellings_are_exact_target_text(span, text):
    assert resolve_span(span).text == text


def test_incomplete_joined_word_and_old_binding_still_fail():
    for word in (13, 14):
        with pytest.raises(ReferenceError) as error:
            resolve_span(SourceSpan(5, 72, word, word))
        assert error.value.code == "mapping_boundary"
    dataset = fixture_dataset()
    with pytest.raises(ReferenceError) as error:
        replace(
            dataset,
            bindings=(replace(dataset.bindings[0], mapping_revision="simple-uthmani-2"),),
        ).validate()
    assert error.value.code == "stale_translation"


def approval_fixture():
    root = Path(__file__).resolve().parents[1]
    approvals = json.loads(
        (root / "scripts/data/reviewed-word-boundaries.json").read_text("utf-8")
    )
    approval = next(a for a in approvals if a.get("partitions"))
    text = " " * 98 + approval["target_text"] + " "
    words = ["unused"] * 12 + approval["source_text"].split()
    return approval, words, text


def test_authored_partitions_preserve_source_and_target_coverage():
    approval, words, text = approval_fixture()
    assert reviewed_groups(approval, [13, 15, 98, 122, False], words, text) == [
        [13, 14, 98, 108, True], [15, 15, 108, 122, True]
    ]


@pytest.mark.parametrize("defect", ["offset", "source", "text", "coverage", "overlap"])
def test_builder_refuses_unverifiable_or_incomplete_partitions(defect):
    approval, words, text = approval_fixture()
    changed = copy.deepcopy(approval)
    parts = changed["partitions"]
    if defect == "offset":
        parts[0]["target_range"][1] -= 1
    elif defect == "source":
        parts[0]["source_text"] = "changed"
    elif defect == "text":
        parts[1]["target_text"] = "changed"
    elif defect == "coverage":
        parts.pop()
    else:
        parts[1]["source_words"][0] = 14
    with pytest.raises(ValueError, match="Reviewed partitions"):
        reviewed_groups(changed, [13, 15, 98, 122, False], words, text)
