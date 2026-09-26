from __future__ import annotations

import builtins
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from quran_image_generator import cli
from quran_image_generator import generator as generator_module
from quran_image_generator.models import GenerationRequest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_config(path: Path, **values: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(values), encoding="utf-8")
    return path


def test_help_has_no_runtime_imports_or_filesystem_side_effects(tmp_path):
    outside = tmp_path / "outside directory with spaces"
    outside.mkdir()
    hook_directory = tmp_path / "import hook"
    hook_directory.mkdir()
    (hook_directory / "sitecustomize.py").write_text(
        "import builtins\n"
        "original_import = builtins.__import__\n"
        "def guarded_import(name, *args, **kwargs):\n"
        "    if name.split('.')[0] in {'instagrapi', 'requests', 'wand', 'yaml'}:\n"
        "        raise ImportError(f'unexpected runtime import: {name}')\n"
        "    return original_import(name, *args, **kwargs)\n"
        "builtins.__import__ = guarded_import\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(hook_directory), str(PROJECT_ROOT / "src"))
    )

    completed = subprocess.run(
        [sys.executable, "-m", "quran_image_generator", "--help"],
        cwd=outside,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--chapter" in completed.stdout
    assert "--no-open" in completed.stdout
    assert "No selector: repeat with interactive chapter and verse prompts." in completed.stdout
    assert "--chapter/--start/--end or --random: generate once" in completed.stdout
    assert "One-shot mode defaults to --no-open; pass --open" in completed.stdout
    assert "quran-image-generator --chapter 2 --start 255 --end 257" in completed.stdout
    assert list(outside.iterdir()) == []


def test_source_checkout_launcher_bootstraps_src_and_keeps_help_lazy(tmp_path):
    hook_directory = tmp_path / "source launcher import hook"
    hook_directory.mkdir()
    (hook_directory / "sitecustomize.py").write_text(
        "import builtins\n"
        "original_import = builtins.__import__\n"
        "def guarded_import(name, *args, **kwargs):\n"
        "    if name.split('.')[0] in {'instagrapi', 'requests', 'wand', 'yaml'}:\n"
        "        raise ImportError(f'unexpected runtime import: {name}')\n"
        "    return original_import(name, *args, **kwargs)\n"
        "builtins.__import__ = guarded_import\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(hook_directory)

    completed = subprocess.run(
        [sys.executable, "main.py", "--help"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--output-dir" in completed.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ["--chapter", "1"],
        ["--chapter", "1", "--start", "1"],
        ["--start", "1", "--end", "1"],
        [
            "--random",
            "--chapter",
            "1",
            "--start",
            "1",
            "--end",
            "1",
        ],
    ],
)
def test_invalid_selection_flags_fail_before_runtime_loading(arguments):
    with pytest.raises(SystemExit) as caught:
        cli.main(arguments)

    assert caught.value.code == 2


def test_out_of_bounds_range_fails_before_config_or_output_side_effects(tmp_path):
    output_directory = tmp_path / "must not be created"

    with pytest.raises(SystemExit) as caught:
        cli.main(
            [
                "--config",
                str(tmp_path / "missing-config.yaml"),
                "--output-dir",
                str(output_directory),
                "--chapter",
                "1",
                "--start",
                "1",
                "--end",
                "8",
            ]
        )

    assert caught.value.code == 2
    assert not output_directory.exists()


def test_explicit_range_is_one_shot_headless_and_honors_output_override(
    monkeypatch, tmp_path
):
    outside = tmp_path / "working directory with spaces"
    outside.mkdir()
    config_path = _write_config(
        tmp_path / "config directory with spaces" / "settings.yaml",
        **{
            "output path": "ignored-output",
            "translation languages": "",
            "upload": "ask",
        },
    )
    generated: list[tuple[object, GenerationRequest, bool, bool]] = []

    class FakeGenerator:
        def __init__(self, settings):
            self.settings = settings

        def generate(self, request, *, publish, open_output):
            generated.append((self.settings, request, publish, open_output))
            return SimpleNamespace(path=self.settings.output_path / "image.png")

        def publish(self, path):
            pytest.fail(f"one-shot upload prompt unexpectedly published {path}")

    monkeypatch.chdir(outside)
    monkeypatch.setattr(
        generator_module, "build_generator", lambda settings: FakeGenerator(settings)
    )
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt="": pytest.fail(f"one-shot command prompted: {prompt}"),
    )

    result = cli.main(
        [
            "--config",
            str(config_path),
            "--output-dir",
            "generated images",
            "--chapter",
            "1",
            "--start",
            "1",
            "--end",
            "1",
        ]
    )

    expected_output = outside / "generated images"
    assert result == 0
    assert expected_output.is_dir()
    assert not (config_path.parent / "ignored-output").exists()
    assert len(generated) == 1
    settings, request, publish, open_output = generated[0]
    assert settings.output_path == expected_output
    assert request == GenerationRequest(1, 1, 1)
    assert publish is False
    assert open_output is False


def test_interactive_mode_keeps_prompt_and_repeat_flow(monkeypatch, tmp_path):
    config_path = _write_config(
        tmp_path / "config.yaml",
        **{"translation languages": "", "upload": False},
    )
    generated: list[GenerationRequest] = []
    answers = iter(("1", "1", "1", "n"))

    class FakeGenerator:
        def generate(self, request, *, publish, open_output):
            generated.append(request)
            assert publish is False
            assert open_output is True
            return SimpleNamespace(path=tmp_path / "image.png")

    monkeypatch.setattr(
        generator_module, "build_generator", lambda settings: FakeGenerator()
    )
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    assert cli.main(["--config", str(config_path)]) == 0
    assert generated == [GenerationRequest(1, 1, 1)]


@pytest.mark.parametrize(
    ("platform", "command"),
    (("darwin", "open"), ("linux", "xdg-open")),
)
def test_image_opener_uses_argument_vector(monkeypatch, tmp_path, platform, command):
    image_path = tmp_path / "generated image.png"
    calls = []
    monkeypatch.setattr(generator_module.sys, "platform", platform)
    monkeypatch.setattr(
        generator_module.subprocess,
        "Popen",
        lambda arguments: calls.append(arguments),
    )

    generator_module._open_image(image_path)

    assert calls == [[command, str(image_path.resolve())]]


def test_image_opener_uses_startfile_on_windows(monkeypatch, tmp_path):
    image_path = tmp_path / "generated image.png"
    calls = []
    monkeypatch.setattr(generator_module.sys, "platform", "win32")
    monkeypatch.setattr(
        generator_module.os,
        "startfile",
        lambda path: calls.append(path),
        raising=False,
    )

    generator_module._open_image(image_path)

    assert calls == [str(image_path.resolve())]
