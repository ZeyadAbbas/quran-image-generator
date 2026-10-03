import json
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
    assert BindingDataset.from_dict(dataset.to_dict()) == dataset
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


def test_edits_and_reordered_segments_need_explicit_edit_provenance():
    dataset = fixture_dataset()
    binding = dataset.bindings[0]
    for segments in (
        ("Allah's promise is false.",),
        ("Allah's promise is true.", "staying there forever."),
    ):
        changed = replace(dataset, bindings=(replace(binding, segments=segments),))
        with pytest.raises(ReferenceError, match="edited=true"):
            changed.validate()
        changed = replace(
            changed, bindings=(replace(changed.bindings[0], edited=True),)
        )
        changed.validate()
        assert changed.lookup(binding.binding_id, binding.spans).edited
    reflowed = replace(
        dataset,
        bindings=(
            replace(
                binding, segments=("staying there forever.", "Allah's promise is true.")
            ),
        ),
    )
    reflowed.validate()
    assert not reflowed.bindings[0].edited


@pytest.mark.parametrize("change", [{"unknown": 1}, {"schema_version": True}])
def test_import_uses_the_same_strict_schema_as_machine_requests(change):
    data = json.loads(json.dumps(fixture_dataset().to_dict()))
    with pytest.raises(ReferenceError) as error:
        BindingDataset.from_dict({**data, **change})
    assert error.value.code == "invalid_translation"


def test_changed_translation_version_invalidates_previously_reviewed_bindings():
    dataset = fixture_dataset()
    with pytest.raises(ReferenceError) as error:
        replace(dataset, source=replace(dataset.source, version="2")).validate()
    assert error.value.code == "stale_translation"


def test_revision_three_bindings_remain_exact_and_stale_content_is_rejected():
    dataset = fixture_dataset()
    binding = replace(dataset.bindings[0], mapping_revision="simple-uthmani-3")
    replace(dataset, bindings=(binding,)).validate()
    for change in ({"arabic_sha256": "0" * 64}, {"mapping_revision": "unknown"},
                   {"spans": (SourceSpan(31, 9, 2, 5),)}):
        with pytest.raises(ReferenceError):
            replace(dataset, bindings=(replace(binding, **change),)).validate()
