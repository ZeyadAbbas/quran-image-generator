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
