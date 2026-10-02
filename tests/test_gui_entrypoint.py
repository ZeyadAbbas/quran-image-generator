from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _toml_table(source: str, name: str) -> str:
    """Return one simple table body without requiring Python 3.11's tomllib."""

    marker = f"[{name}]\n"
    _prefix, separator, remainder = source.partition(marker)
    assert separator, f"missing {marker.strip()}"
    return remainder.partition("\n[")[0]


def _source_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    environment.pop("DISPLAY", None)
    environment.pop("WAYLAND_DISPLAY", None)
    return environment


def test_cli_and_headless_state_import_without_tkinter(tmp_path):
    script = (
        "import builtins, sys; original = builtins.__import__; "
        "builtins.__import__ = lambda name, *a, **k: "
        "(_ for _ in ()).throw(ImportError(name)) "
        "if name.split('.')[0] == 'tkinter' else original(name, *a, **k); "
        "import quran_image_generator; "
        "from quran_image_generator import cli, gui_state; "
        "assert 'tkinter' not in sys.modules"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=_source_environment(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_gui_help_needs_neither_tkinter_nor_display(tmp_path):
    script = (
        "import builtins; original = builtins.__import__; "
        "builtins.__import__ = lambda name, *a, **k: "
        "(_ for _ in ()).throw(ImportError(name)) "
        "if name.split('.')[0] == 'tkinter' else original(name, *a, **k); "
        "from quran_image_generator.gui_cli import main; "
        "main(['--help'])"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=_source_environment(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "quran-image-generator-gui" in completed.stdout
    assert "--config" in completed.stdout
    normalized_help = " ".join(completed.stdout.split())
    assert "Bundled Arabic content works offline" in normalized_help
    assert "QuranEnc" in normalized_help


def test_missing_tkinter_has_a_concise_launcher_error(tmp_path):
    script = (
        "import builtins; original = builtins.__import__; "
        "builtins.__import__ = lambda name, *a, **k: "
        "(_ for _ in ()).throw(ImportError("
        '"No module named tkinter", name="tkinter")) '
        "if name.split('.')[0] == 'tkinter' else original(name, *a, **k); "
        "from quran_image_generator.gui_cli import main; "
        "raise SystemExit(main([]))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=_source_environment(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "tkinter support" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_display_failure_is_concise(monkeypatch, capsys):
    from quran_image_generator import gui

    monkeypatch.setattr(
        gui.tk,
        "Tk",
        lambda: (_ for _ in ()).throw(gui.tk.TclError("secret display detail")),
    )

    assert gui.launch() == 2
    error = capsys.readouterr().err
    assert "could not open a display" in error
    assert "secret display detail" not in error


def test_renderer_setup_failure_keeps_non_rendering_gui_features_available(
    settings_factory,
):
    from quran_image_generator import gui

    def fail_setup(*_args, **_kwargs):
        raise ImportError("private native loader detail")

    workflow, message = gui._create_preview_workflow(
        settings_factory(),
        object(),
        generator_builder=fail_setup,
    )

    assert workflow is None
    assert message is not None
    assert "Wand and ImageMagick" in message
    assert "Configuration and Help remain available" in message
    assert "private native loader detail" not in message


def test_preview_display_failure_preserves_the_visible_preview(
    monkeypatch, settings_factory, tmp_path
):
    from hashlib import sha256

    from quran_image_generator import gui
    from quran_image_generator.gui_state import (
        PreviewArtifact,
        RevisionGate,
        WorkerResult,
    )
    from quran_image_generator.models import (
        Chapter,
        GenerationRequest,
        Passage,
        Verse,
    )

    class Variable:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    settings = settings_factory()
    request = GenerationRequest(1, 1, 1)
    passage = Passage(
        Chapter(1, "Al-Fatihah", 7),
        (Verse(1, "1:1", ("word",), ()),),
    )

    def artifact(name, payload):
        path = tmp_path / name
        path.write_bytes(payload)
        return PreviewArtifact(
            0,
            request,
            (),
            settings,
            passage,
            path,
            sha256(payload).hexdigest(),
        )

    previous = artifact("previous.png", b"previous")
    candidate = artifact("candidate.png", b"candidate")
    gate = RevisionGate()
    first_token = gate.begin("preview")
    assert gate.accept_preview(first_token, previous)
    candidate_token = gate.begin("preview")

    app = object.__new__(gui.QuranImageGeneratorApp)
    app._gate = gate
    app._shown_preview_artifact = previous
    app._open_after_jobs = set()
    app._status_var = Variable("")
    old_source = object()
    old_display = object()
    app._preview_source_image = old_source
    app._preview_display_image = old_display
    app._preview_label = object()
    app._preview_info_var = Variable("Previous preview")
    monkeypatch.setattr(
        gui.tk,
        "PhotoImage",
        lambda **_kwargs: (_ for _ in ()).throw(gui.tk.TclError()),
    )

    app._handle_worker_result(WorkerResult(candidate_token, value=candidate))

    assert gate.current_preview() == previous
    assert app._shown_preview_artifact == previous
    assert app._preview_source_image is old_source
    assert app._preview_display_image is old_display
    assert previous.path.is_file()
    assert not candidate.path.exists()
    assert "could not display" in app._status_var.get()


def test_color_picker_falls_back_for_invalid_input_and_handles_tcl_error(monkeypatch):
    from quran_image_generator import gui

    class Variable:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    app = object.__new__(gui.QuranImageGeneratorApp)
    app.root = object()
    app._status_var = Variable("")
    color = Variable("not-a-color")
    seen = []

    def choose_color(**options):
        seen.append(options["color"])
        return None, None

    monkeypatch.setattr(gui.colorchooser, "askcolor", choose_color)
    app._choose_color(color)
    assert seen == ["#000000"]

    monkeypatch.setattr(
        gui.colorchooser,
        "askcolor",
        lambda **_options: (_ for _ in ()).throw(gui.tk.TclError()),
    )
    app._choose_color(color)
    assert "#RRGGBB" in app._status_var.get()


def test_gui_entrypoint_is_separate_and_adds_no_dependency():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    scripts = _toml_table(pyproject, "project.scripts").splitlines()
    gui_scripts = _toml_table(pyproject, "project.gui-scripts").splitlines()
    project = _toml_table(pyproject, "project").casefold()

    assert scripts == [
        'quran-image-generator = "quran_image_generator.cli:main"',
        'quran-caption-render = "quran_image_generator.machine_cli:main"',
    ]
    assert gui_scripts == [
        'quran-image-generator-gui = "quran_image_generator.gui_cli:main"'
    ]
    # Pillow is now a headless scene-rendering dependency; Tk still adds no GUI framework.
    assert all(name not in project for name in ("pyqt", "pyside", "electron"))
