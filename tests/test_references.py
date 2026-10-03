import pytest

from quran_image_generator.content import _load_bundled_corpus
from quran_image_generator.references import (
    CorpusIdentity,
    ReferenceError,
    SourceSpan,
    bridge_data,
    resolve_span,
)


def test_exhaustive_coverage_and_exact_reconstruction():
    corpus = _load_bundled_corpus()
    data = bridge_data()
    assert len(data["verses"]) == 6237
    for key, record in data["verses"].items():
        s, a = map(int, key.split(":"))
        result = resolve_span(SourceSpan(s, a, 1, record["word_count"]))
        assert result.text == corpus.verses[(1, 1) if s == 0 else (s, a)][record["offset"]:]
        assert result.starts_ayah and result.ends_ayah
        assert all(g[2] <= g[3] for g in record["groups"])
        assert [g[2] for g in record["groups"]] == sorted(g[2] for g in record["groups"])
        verse = corpus.verses[(1, 1) if s == 0 else (s, a)]
        assert "".join(verse[g[2]:g[3]] for g in record["groups"]) == verse[record["offset"]:]
        assert [word for g in record["groups"] for word in range(g[0], g[1]+1)] == list(range(1, record["word_count"]+1))
    assert data["review"]  # Unapproved orthography never disappears silently.


@pytest.mark.parametrize("s,a", [(2,1),(2,33),(9,1),(27,30),(2,255),(17,13),(31,11),(39,30),(5,73)])
def test_fixture_identity_and_repeatability(s, a):
    n = bridge_data()["verses"][f"{s}:{a}"]["word_count"]
    assert resolve_span(SourceSpan(s,a,1,n)) == resolve_span(SourceSpan(s,a,1,n))


def test_joined_boundary_is_explicit_and_basmala_is_separate():
    with pytest.raises(ReferenceError, match="joined"):
        resolve_span(SourceSpan(2,21,1,1))
    assert resolve_span(SourceSpan(2,21,1,2)).text.startswith("يَٰٓأَيُّهَا")
    assert resolve_span(SourceSpan(0,0,1,4)).text == resolve_span(SourceSpan(1,1,1,4)).text
    assert "بِسْمِ" not in resolve_span(SourceSpan(9,1,1,1)).text
    with pytest.raises(ReferenceError) as error:
        resolve_span(SourceSpan(31,9,1,5), CorpusIdentity(sha256="wrong"))
    assert error.value.code == "unsupported_corpus"


@pytest.mark.parametrize("first,last", [(1, 5), (6, 11), (12, 16), (17, 23), (24, 29)])
def test_legacy_recording_yunus_88_segments_are_exact_verbatim_slices(first, last):
    record = bridge_data()["verses"]["10:88"]
    selected = [g for g in record["groups"] if first <= g[0] <= last]
    result = resolve_span(SourceSpan(10, 88, first, last))
    verse = _load_bundled_corpus().verses[(10, 88)]
    assert result.text == verse[selected[0][2]:selected[-1][3]].rstrip()
    assert result.starts_ayah is (first == 1)
    assert result.ends_ayah is (last == 29)


@pytest.mark.parametrize("word,text", [(5, "ءَاتَيْتَ"), (7, "وَمَلَأَهُۥ"),
                                      (11, "ٱلْحَيَوٰةِ")])
def test_reviewed_yunus_88_spellings_are_selectable_individually(word, text):
    assert resolve_span(SourceSpan(10, 88, word, word)).text == text
    assert not any(r["verse"] == "10:88" and r["source_words"] == [word, word]
                   for r in bridge_data()["review"])


def test_unreviewed_spellings_and_joined_boundaries_still_fail():
    with pytest.raises(ReferenceError) as error:
        resolve_span(SourceSpan(2, 3, 5, 5))
    assert error.value.code == "mapping_boundary"
    with pytest.raises(ReferenceError) as error:
        resolve_span(SourceSpan(2, 21, 1, 1))
    assert error.value.code == "mapping_boundary"
