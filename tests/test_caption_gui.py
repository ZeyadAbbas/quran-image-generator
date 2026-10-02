"""Exercise real native controls and public rendering; no external HTTP or user assets."""

import copy
import json
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from quran_image_generator.api import execute_request
from quran_image_generator.caption_editor import (
    ASSET_ROLES,
    LAYER_ROLES,
    STYLE_FIELDS,
    CaptionDocument,
    compose_caption,
)
from quran_image_generator.references import ReferenceError
from quran_image_generator.resources import asset_path


@pytest.fixture(scope="module")
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Native Tk needs a display; CI supplies Xvfb or Windows: {error}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def studio(tk_root, monkeypatch, tmp_path):
    from quran_image_generator import caption_gui

    root = caption_gui.tk.Toplevel(tk_root)
    root.withdraw()

    # An unexpected modal error must fail a test instead of blocking CI.
    def error(*args, **kwargs):
        pytest.fail(f"Unexpected GUI error: {args}")

    monkeypatch.setattr(caption_gui.messagebox, "showerror", error)
    monkeypatch.setattr(caption_gui.messagebox, "askyesnocancel", lambda *a, **k: False)
    app = caption_gui.CaptionStudio(root)
    app._vars["output_directory"].set(str(tmp_path / "GUI export"))
    root.update()
    yield app
    app.close(discard=True)


def test_close_cancel_preserves_unsaved_request(studio, monkeypatch):
    from quran_image_generator import caption_gui

    monkeypatch.setattr(caption_gui.messagebox, "askyesnocancel", lambda *a, **k: None)
    assert not studio.close()
    assert not studio._closed
    assert studio.window.winfo_exists()


def test_close_during_render_cancels_without_touching_destroyed_widgets(
    studio, monkeypatch
):
    from quran_image_generator import caption_gui

    entered = threading.Event()

    def render(*args, **kwargs):
        entered.set()
        deadline = time.monotonic() + 10
        while not kwargs["cancelled"]():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        return execute_request(*args, **kwargs)

    monkeypatch.setattr(caption_gui, "execute_request", render)
    studio._start("preview")
    assert entered.wait(10)
    assert studio.close(discard=True)
    deadline = time.monotonic() + 10
    while studio._worker.is_alive:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert not Path(studio._temporary.name).exists()


def test_partial_batch_failed_caption_cannot_be_saved(studio):
    app = studio
    app._duplicate()
    app.document.data["cues"][1]["spans"][0]["word_end"] = 1000
    app._fill_cue()
    app._vars["error_mode"].set("per_cue")
    app._start("preview")
    settle(app)
    assert app._response["status"] == "partial"
    assert str(app._save_png["state"]) == "disabled"
    app._cues.selection_set("0")
    app._select_cue()
    assert str(app._save_png["state"]) == "normal"


def settle(app, timeout=30):
    deadline = time.monotonic() + timeout
    while app._worker.busy:
        app.window.update()
        time.sleep(0.01)
        assert time.monotonic() < deadline, "GUI worker did not finish"
    app._poll()
    app.window.update()


def set_source(app, *, approved=True):
    for name, value in dict(
        provider="local",
        resource="GUI fixture",
        version="1",
        translator="Test author",
        license="test only",
        attribution="Test fixture",
        direction="ltr",
    ).items():
        app._vars["source_" + name].set(value)
    app._vars["binding_id"].set("gui-phrase")
    app._vars["translation_policy"].set("required")
    app._source_text.insert("1.0", "Authored caption for testing.")
    app._segments.insert("1.0", "Authored caption\nfor testing.")
    app.window.update()
    app._vars["reviewer"].set("Test reviewer")
    app._vars["binding_approved"].set(approved)
    app._apply_binding()


def test_all_roles_and_styles_have_native_controls(studio):
    from quran_image_generator.caption_gui import ROLE_LABELS

    app = studio
    assert set(app._styles) == set(STYLE_FIELDS)
    assert tuple(app._layer_choice["values"]) == tuple(
        ROLE_LABELS[r] for r in LAYER_ROLES
    )
    assert tuple(app._asset_choice["values"]) == tuple(
        ROLE_LABELS[r] for r in ASSET_ROLES
    )
    assert len(app._tabs.tabs()) == 6
    for role in LAYER_ROLES:
        app._change_layer(role)
        app._styles["font_size"].set("24.25")
        app._styles["anchor"].set("0.5, 0.4")
        app._styles["opacity"].set("0.75")
        app._styles["horizontal_scale"].set("1.15")
        app._apply_layer()
    app._collect()
    styles = app.document.profile()["styles"]
    assert set(styles) == set(LAYER_ROLES)
    assert all(
        s["font_size"] == 24.25 and s["horizontal_scale"] == 1.15
        for s in styles.values()
    )


def test_font_selection_preserves_style_edits_and_pins_file(studio):
    app = studio
    app._styles["font_size"].set("29.25")
    font = str(asset_path("fonts", "quran_font.ttf"))
    app._vars["asset_path"].set(font)
    app._vars["asset_license"].set("Bundled notice")
    app._vars["asset_attribution"].set("Test")
    app._apply_asset(force=True)
    assert app.document.styles("arabic")["font_size"] == 29.25
    assert (
        app._vars["asset_sha"].get() == app.document.data["assets"]["arabic"]["sha256"]
    )
    assert app.document.styles("arabic")["sha256"] == app._vars["asset_sha"].get()


def test_roundtrip_gui_request_replay_and_transparent_png(
    studio, monkeypatch, tmp_path
):
    from quran_image_generator import caption_gui

    app = studio
    set_source(app)
    app._vars["titles"].set(True)
    app._vars["cropped"].set(True)
    app._vars["arabic_title"].set("الفاتحة")
    app._vars["latin_title"].set("Custom title")
    app._styles["outline_width"].set("0.4")
    app._styles["shadow_offset"].set("1, 1")
    app._styles["shadow_opacity"].set("0.4")
    logo = tmp_path / "my logo.png"
    Image.new("RGBA", (24, 16), "#FF000080").save(logo)
    app._change_asset("logo")
    app._vars["asset_path"].set(str(logo))
    app._vars["asset_license"].set("test only")
    app._vars["asset_attribution"].set("Test author")
    app._apply_asset(force=True)
    app._duplicate()
    app._vars["profile_approval"].set("approved")
    assert len(app.document.data["cues"]) == 2
    app._vars["start_seconds"].set("5")
    app._vars["end_seconds"].set("7")
    saved = tmp_path / "GUI request.json"
    monkeypatch.setattr(
        caption_gui.filedialog, "asksaveasfilename", lambda **k: str(saved)
    )
    assert app.save_request()
    loaded = CaptionDocument.load(saved)
    assert loaded.request().to_dict() == app.document.request().to_dict()
    app._start("preview")
    settle(app)
    assert app._response["status"] == "complete", app._status.get()
    assert str(app._save_png["state"]) == "normal"
    replay = execute_request(loaded.request()).to_dict()
    assert replay["status"] == "complete"
    assert [a["sha256"] for a in replay["assets"]] == [
        a["sha256"] for a in app._response["assets"]
    ]
    assert {role for a in replay["assets"] for role in a["roles"]} == set(LAYER_ROLES)
    png = tmp_path / "combined.png"
    monkeypatch.setattr(
        caption_gui.filedialog, "asksaveasfilename", lambda **k: str(png)
    )
    app.save_png()
    with Image.open(png) as image:
        assert image.size == (576, 1024)
        assert image.getpixel((0, 0))[3] == 0
        assert image.tobytes() == compose_caption(replay, 1, image.size).tobytes()


def test_range_order_repeat_and_basmala_controls(studio):
    app = studio
    for name, value in dict(surah=31, ayah=9, first=1, last=5).items():
        app._vars["range_" + name].set(value)
    app._add_range(replace_selected=True)
    app._basmala()
    assert app.document.spans(0)[-1].surah == 0
    app._spans.selection_set("1")
    app._move_range(-1)
    assert app.document.spans(0)[0].surah == 0
    app._duplicate()
    assert app.document.spans(1) == app.document.spans(0)
    app._vars["cue_id"].set("second occurrence")
    app._move_cue(-1)
    assert app.document.data["cues"][0]["cue_id"] == "second occurrence"


def test_translation_edits_and_source_identity_revoke_review(studio):
    app = studio
    set_source(app)
    app._segments.insert("end", " changed")
    app.window.update()
    assert not app._vars["binding_approved"].get()
    with pytest.raises(ReferenceError, match="edited=true"):
        app._apply_binding()
    app._vars["edited"].set(True)
    app._apply_binding()
    assert app.document.dataset().bindings[0].edited
    assert app.document.dataset().bindings[0].review_status == "needs_review"
    app._vars["binding_approved"].set(True)
    app._vars["source_version"].set("2")
    assert not app._vars["binding_approved"].get()
    app._apply_binding()
    assert (
        app.document.dataset().bindings[0].source_identity_sha256
        == app.document.dataset().source.identity_sha256
    )


def test_layer_edit_revokes_style_approval(studio):
    app = studio
    app._vars["profile_approval"].set("approved")
    app._styles["font_size"].set("30.5")
    assert app._vars["profile_approval"].get() == "needs_review"
    app._vars["profile_approval"].set("approved")
    app._vars["asset_path"].set("new font.ttf")
    assert app._vars["profile_approval"].get() == "needs_review"


def test_invalid_form_does_not_partially_overwrite_document(studio):
    app = studio
    before = copy.deepcopy(app.document.data)
    app._vars["cue_id"].set("new id")
    app._vars["height"].set("invalid")
    with pytest.raises(ValueError):
        app._collect()
    assert app.document.data == before


def test_changed_settings_during_render_cannot_be_saved(studio, monkeypatch):
    from quran_image_generator import caption_gui

    app = studio
    entered, release = threading.Event(), threading.Event()

    def held_render(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return execute_request(*args, **kwargs)

    monkeypatch.setattr(caption_gui, "execute_request", held_render)
    app._start("preview")
    assert entered.wait(10)
    app._styles["font_size"].set("30.25")
    release.set()
    settle(app)
    assert app._response is None
    with pytest.raises(ValueError, match="Refresh"):
        app.save_png()
    assert "changed during rendering" in app._status.get()


def test_cancel_and_export_use_the_same_worker_and_contract(studio, monkeypatch):
    from quran_image_generator import caption_gui

    app = studio
    entered = threading.Event()

    def wait_for_cancel(*args, **kwargs):
        entered.set()
        deadline = time.monotonic() + 10
        while not kwargs["cancelled"]():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        return execute_request(*args, **kwargs)

    monkeypatch.setattr(caption_gui, "execute_request", wait_for_cancel)
    app._start("preview")
    assert entered.wait(10)
    app._worker.cancel()
    settle(app)
    assert "cancelled" in app._status.get()
    assert app._response is None
    monkeypatch.setattr(caption_gui, "execute_request", execute_request)
    app._vars["profile_approval"].set("approved")
    app._start("export")
    settle(app)
    manifest = Path(app._response["job_directory"]) / "manifest.json"
    assert manifest.is_file()
    assert json.loads(manifest.read_text("utf-8"))["status"] == "complete"


def test_import_styles_preserves_uncommitted_canvas_and_caption_fields(
    studio, monkeypatch, tmp_path
):
    from quran_image_generator import caption_gui

    app = studio
    app._vars["width"].set("720")
    app._vars["cue_id"].set("my caption")
    profile = tmp_path / "styles.json"
    profile.write_text(
        json.dumps(
            {
                "id": "any style",
                "revision": "2",
                "approval": "approved",
                "styles": {"arabic": {"font_size": 28.5}},
                "provenance": {"author": "Any user"},
            }
        ),
        "utf-8",
    )
    monkeypatch.setattr(
        caption_gui.filedialog, "askopenfilename", lambda **k: str(profile)
    )
    app._import_profile()
    app._collect()
    assert app.document.data["canvas"]["width"] == 720
    assert app.document.data["cues"][0]["cue_id"] == "my caption"
    assert app.document.styles("arabic")["font_size"] == 28.5


def test_setup_and_layout_report_without_png_files(studio):
    app = studio
    app._start("preflight")
    settle(app)
    assert app._response is None
    assert "corpus: verified" in app._diagnostics.get("1.0", "end")
    app._start("layout")
    settle(app)
    assert app._response is None
    assert "Arabic caption" in app._diagnostics.get("1.0", "end")
    assert not list(Path(app._vars["output_directory"].get()).rglob("*.png"))


def test_snapshot_pinning_and_local_copy_use_native_controls(
    studio, monkeypatch, tmp_path
):
    from quran_image_generator import caption_gui

    app = studio
    set_source(app)
    directory = tmp_path / "Pinned bindings"
    monkeypatch.setattr(
        caption_gui.filedialog, "askdirectory", lambda **k: str(directory)
    )
    app._pin_dataset()
    assert "translation_snapshot" in app.document.data
    assert str(app._segments["state"]) == "disabled"
    assert app._vars["binding_approved"].get()
    snapshot_file = next(directory.glob("*.json"))
    before = snapshot_file.read_bytes()
    app._edit_snapshot()
    assert "translation_snapshot" not in app.document.data
    assert str(app._segments["state"]) == "normal"
    assert snapshot_file.read_bytes() == before


def test_import_bindings_and_snapshots_preserve_pending_caption_fields(
    studio, monkeypatch, tmp_path
):
    from test_bindings import fixture_dataset

    from quran_image_generator import caption_gui
    from quran_image_generator.bindings import export_bindings
    from quran_image_generator.snapshots import SnapshotStore

    app = studio
    dataset = fixture_dataset()
    file = tmp_path / "bindings.json"
    export_bindings(dataset, file)
    monkeypatch.setattr(
        caption_gui.filedialog, "askopenfilename", lambda **k: str(file)
    )
    app._vars["cue_id"].set("Pending caption name")
    app._vars["latin_title"].set("Pending title")
    app._vars["translation_policy"].set("review")
    app._vars["start_seconds"].set("1.2")
    app._import_bindings()
    assert app._vars["cue_id"].get() == "Pending caption name"
    assert app._vars["latin_title"].get() == "Pending title"
    assert app._vars["translation_policy"].get() == "review"
    assert app.document.data["cues"][0]["metadata"]["start_seconds"] == 1.2
    store = SnapshotStore(tmp_path / "Snapshot")
    pin = store.import_dataset(dataset)
    monkeypatch.setattr(
        caption_gui.filedialog,
        "askopenfilename",
        lambda **k: str(store.directory / f"{pin}.json"),
    )
    app._vars["latin_title"].set("Before snapshot")
    app._open_snapshot()
    assert app._vars["latin_title"].get() == "Before snapshot"
    app._vars["latin_title"].set("Before local copy")
    app._edit_snapshot()
    assert app._vars["latin_title"].get() == "Before local copy"


def test_close_invalid_save_preserves_editor_and_shows_error(studio, monkeypatch):
    from quran_image_generator import caption_gui

    errors = []
    monkeypatch.setattr(caption_gui.messagebox, "askyesnocancel", lambda *a, **k: True)
    monkeypatch.setattr(
        caption_gui.messagebox, "showerror", lambda *a, **k: errors.append(a)
    )
    studio._vars["height"].set("invalid")
    assert not studio.close()
    assert errors and not studio._closed and studio.window.winfo_exists()


def test_whole_verse_source_loading_preserves_provenance(studio, monkeypatch, tmp_path):
    from quran_image_generator import caption_gui
    from quran_image_generator.snapshots import SnapshotStore

    app = studio
    store = SnapshotStore(tmp_path / "Sources")
    digest = store.put(
        {
            "kind": "whole_ayah_translation",
            "schema_version": 1,
            "source": {
                "provider": "QuranEnc",
                "resource_id": "example",
                "version": "1",
                "author": "Test author",
                "license": "Test terms",
                "attribution": "Test fixture",
                "direction": "ltr",
            },
            "verses": {"1:1": "Test whole verse wording."},
        }
    )
    monkeypatch.setattr(
        caption_gui.filedialog,
        "askopenfilename",
        lambda **k: str(store.directory / f"{digest}.json"),
    )
    app._read_source()
    assert app._vars["source_version"].get() == f"1; snapshot:{digest}"
    assert app._source_text.get("1.0", "end-1c") == "Test whole verse wording."
    assert app._segments.get("1.0", "end-1c") == ""
    assert not app._vars["binding_approved"].get()
    assert app.document.dataset() is None


def test_font_glyph_branding_and_quotation_number_controls(studio):
    app = studio
    app._vars["quotations"].set(True)
    app._vars["verse_numbers"].set(True)
    app._styles["quote_open"].set("(")
    app._styles["quote_close"].set(")")
    app._styles["marker_prefix"].set("(")
    app._styles["marker_suffix"].set(")")
    app._styles["numeral_system"].set("latin")
    app._styles["decoration_scale"].set("1.1")
    app._styles["suffix_offset"].set("-2")
    app._change_asset("decorations")
    app._vars["asset_path"].set(
        str(asset_path("fonts", "multilingual_fonts", "am.ttf"))
    )
    app._apply_asset(force=True)
    app._change_asset("logo")
    app._vars["asset_path"].set(
        str(asset_path("fonts", "multilingual_fonts", "am.ttf"))
    )
    app._vars["asset_glyph"].set("y")
    app._apply_asset(force=True)
    app._start("preview")
    settle(app)
    assert app._response is not None, app._diagnostics.get("1.0", "end")
    assert app._response["status"] == "needs_review"
    plans = {p["layer"]["role"]: p for p in app._response["cues"][0]["layers"]}
    assert plans["logo"]["layer"]["text"] == "y"
    assert plans["arabic"]["layer"]["suffix"] == "(1)"
    assert plans["arabic"]["layer"]["ornaments"]


def test_small_window_pages_remain_scrollable(studio):
    app = studio
    app.window.geometry("1000x700")
    app.window.deiconify()
    app.window.update_idletasks()
    for tab in app._tabs.tabs():
        app._tabs.select(tab)
        app.window.update_idletasks()
        page = app.window.nametowidget(tab)
        assert page.winfo_width() > 0

        # At least one scrollbar on each page keeps oversized content accessible.
        def scrollbars(widget):
            return sum(
                child.winfo_class() == "TScrollbar" for child in widget.winfo_children()
            ) + sum(scrollbars(child) for child in widget.winfo_children())

        assert scrollbars(page) >= 1
    app.window.withdraw()
