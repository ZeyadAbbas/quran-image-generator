from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import tomllib

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
    project = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert project["scripts"] == {
        "quran-image-generator": "quran_image_generator.cli:main"
    }
    assert project["gui-scripts"] == {
        "quran-image-generator-gui": "quran_image_generator.gui_cli:main"
    }
    assert all(
        name not in " ".join(project["dependencies"]).casefold()
        for name in ("pillow", "pyqt", "pyside", "electron")
    )
