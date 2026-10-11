import pytest

from quran_image_generator.excerpts import (
    ExcerptRequest,
    select_excerpt,
    select_excerpts,
)
from quran_image_generator.references import ReferenceError, SourceSpan, bridge_data


def test_reference_phrase_is_exact_and_repeats_keep_occurrences():
    span = SourceSpan(31,9,1,5)
    a,b = select_excerpts(tuple(ExcerptRequest(cid,(span,)) for cid in ("a","b")))
    assert a.text == b.text
    assert a.cue_id != b.cue_id
    assert len(a.spans) == 1 and not a.verse_markers
    assert a.text.endswith("حَقًّا")
    assert "وَهُوَ" not in a.text
    assert len(select_excerpt(ExcerptRequest("c",(SourceSpan(31,11,1,3),))).text.split()) == 3


@pytest.mark.parametrize("s,a", [(39,30),(5,73)])
def test_true_ayah_tail_has_marker(s,a):
    count = bridge_data()["verses"][f"{s}:{a}"]["word_count"]
    tail = select_excerpt(ExcerptRequest("tail", (SourceSpan(s,a,count,count),)))
    assert tail.verse_markers == ((0,a),)
    assert tail.spans[0].ends_ayah and not tail.spans[0].starts_ayah


def test_explicit_translation_policy_and_duplicate_ids():
    with pytest.raises(ReferenceError, match="binding"):
        ExcerptRequest("x",(SourceSpan(31,9,1,5),),translation_policy="required")
    with pytest.raises(ReferenceError, match="unique"):
        select_excerpts((ExcerptRequest("x",(SourceSpan(31,9,1,5),)),)*2)
    assert not select_excerpt(ExcerptRequest("b",(SourceSpan(0,0,1,4),))).verse_markers
