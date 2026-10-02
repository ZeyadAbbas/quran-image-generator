from dataclasses import replace

import pytest

from quran_image_generator.bindings import (
    BindingDataset,
    PhraseBinding,
    TranslationSource,
    export_bindings,
    import_bindings,
    text_hash,
)
from quran_image_generator.excerpts import ExcerptRequest, select_excerpt
from quran_image_generator.references import CorpusIdentity, ReferenceError, SourceSpan


def fixture_dataset():
    spans = (SourceSpan(31, 9, 1, 5),)
    source = "staying there forever. Allah's promise is true."
    binding = PhraseBinding(
        "31-9-prefix",
        "1",
        spans,
        text_hash(select_excerpt(ExcerptRequest("x", spans)).text),
        source,
        text_hash(source),
        (source,),
        "approved",
        "Authored test fixture",
    )
    provenance = TranslationSource(
        "local",
        "authored-fixture",
        "1",
        "Fixture author",
        "test-only",
        "Not an identified creator translation",
    )
    return BindingDataset(
        provenance,
        CorpusIdentity(),
        (replace(binding, source_identity_sha256=provenance.identity_sha256),),
    )


def test_override_round_trip_and_exact_span_binding(tmp_path):
    dataset = fixture_dataset()
    path = tmp_path / "reviewed English.json"
    export_bindings(dataset, path)
    assert import_bindings(path) == dataset
    assert (
        dataset.lookup("31-9-prefix", (SourceSpan(31, 9, 1, 5),)).text
        == dataset.bindings[0].text
    )
    with pytest.raises(ReferenceError, match="exact"):
        dataset.lookup("31-9-prefix", (SourceSpan(31, 9, 1, 4),))


@pytest.mark.parametrize(
    "change",
    [
        dict(source_text="changed"),
        dict(arabic_sha256="wrong"),
        dict(mapping_revision="new"),
        dict(segments=("<b>HTML</b>",)),
    ],
)
def test_changed_provenance_or_hidden_markup_is_rejected(change):
    dataset = fixture_dataset()
    with pytest.raises(ReferenceError):
        replace(dataset, bindings=(replace(dataset.bindings[0], **change),)).validate()


def test_unreviewed_binding_cannot_be_ready():
    dataset = fixture_dataset()
    dataset = replace(
        dataset, bindings=(replace(dataset.bindings[0], review_status="needs_review"),)
    )
    with pytest.raises(ReferenceError) as error:
        dataset.lookup("31-9-prefix", dataset.bindings[0].spans)
    assert error.value.code == "translation_review"
