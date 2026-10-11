import pytest
from test_bindings import fixture_dataset

from quran_image_generator.references import ReferenceError
from quran_image_generator.snapshots import SnapshotStore


def test_snapshot_restart_offline_identity_and_integrity(tmp_path):
    store = SnapshotStore(tmp_path / "offline cache")
    dataset = fixture_dataset()
    digest = store.import_dataset(dataset)
    assert SnapshotStore(store.directory).bindings(digest) == dataset
    assert store.import_dataset(dataset) == digest
    (store.directory / f"{digest}.json").write_text("changed","utf-8")
    with pytest.raises(ReferenceError) as error:
        store.bindings(digest)
    assert error.value.code == "corrupt_snapshot"
    assert not list(store.directory.glob("*.tmp"))


def test_offline_miss_and_path_traversal_are_explicit(tmp_path):
    store = SnapshotStore(tmp_path)
    with pytest.raises(ReferenceError) as error:
        store.read("0"*64)
    assert error.value.code == "offline_translation_miss"
    with pytest.raises(ReferenceError):
        store.read("../../secret")
