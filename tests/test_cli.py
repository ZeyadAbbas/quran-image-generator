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
from quran_image_generator.models import Chapter, GenerationRequest, TranslationResource
from quran_image_generator.publishing import PublishingError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_config(path: Path, **values: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(values), encoding="utf-8")
    return path


def _install_chapter_client(monkeypatch, chapters=None):
    from quran_image_generator import content

    available = chapters or (Chapter(1, "Al-Fatihah", 7),)

    class FakeContentClient:
        def list_chapters(self):
            return available

    client = FakeContentClient()
    monkeypatch.setattr(content, "QuranDataClient", lambda *args, **kwargs: client)
    return client


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
    assert (
        "No selector: repeat with interactive chapter and verse prompts."
        in completed.stdout
    )
    assert "--chapter/--start/--end or --random: generate once" in completed.stdout
    assert "One-shot mode defaults to --no-open; pass --open" in completed.stdout
    assert "quran-image-generator --chapter 2 --start 255 --end 257" in completed.stdout
    assert "--publish {post,story}" in completed.stdout
    assert "--list-translations" in completed.stdout
    assert "--prompt" not in completed.stdout
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


@pytest.mark.parametrize(
    "arguments",
    (
        ["--refresh-catalog"],
        ["--list-translations", "--random"],
        ["--list-translations", "--publish", "post"],
    ),
)
def test_catalog_flags_reject_generation_combinations(arguments):
    with pytest.raises(SystemExit) as caught:
        cli.main(arguments)

    assert caught.value.code == 2


def test_list_translations_is_lazy_and_prints_exact_identity(monkeypatch, capsys):
    from quran_image_generator import content

    resource = TranslationResource(
        "english_saheeh",
        "The Clear Quran",
        "Noor International Center",
        "English",
        "en",
        "1.1.2",
        "ltr",
    )
    second_resource = TranslationResource(
        "uzbek_mansour",
        "Uzbek Translation",
        "Muhammad Sodik Muhammad Yusuf",
        "Uzbek",
        "uz",
        "1.0.0",
        "ltr",
    )
    calls = []

    class FakeClient:
        def translation_catalog(self, *, refresh):
            calls.append(refresh)
            return SimpleNamespace(resources=(resource, second_resource))

        def list_chapters(self):
            pytest.fail("translation listing must not load the chapter catalog")

    monkeypatch.setattr(content, "QuranDataClient", lambda: FakeClient())
    assert cli.main(["--list-translations", "--refresh-catalog"]) == 0
    output = capsys.readouterr().out
    assert calls == [True]
    assert "english_saheeh | en | 1.1.2 | The Clear Quran" in output
    assert "uzbek_mansour | uz | 1.0.0 | Uzbek Translation" in output


def test_list_translations_reports_api_failure_without_traceback(monkeypatch, capsys):
    from quran_image_generator import content
    from quran_image_generator.content import TranslationPayloadError

    class FailingClient:
        def translation_catalog(self, *, refresh):
            raise TranslationPayloadError("invalid translation catalog")

    monkeypatch.setattr(content, "QuranDataClient", lambda: FailingClient())

    with pytest.raises(SystemExit) as caught:
        cli.main(["--list-translations"])

    assert caught.value.code == 1
    error = capsys.readouterr().err
    assert "Translation service error:" in error
    assert "invalid translation catalog" in error
    assert "Traceback" not in error


def test_out_of_bounds_range_fails_before_config_or_output_side_effects(
    monkeypatch, tmp_path
):
    _install_chapter_client(monkeypatch)
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
    expected_client = _install_chapter_client(monkeypatch)
    outside = tmp_path / "working directory with spaces"
    outside.mkdir()
    config_path = _write_config(
        tmp_path / "config directory with spaces" / "settings.yaml",
        **{
            "output path": "ignored-output",
            "translation languages": "",
        },
    )
    generated: list[tuple[object, GenerationRequest, bool]] = []

    class FakeGenerator:
        def __init__(self, settings):
            self.settings = settings

        def generate(self, request, *, open_output):
            generated.append((self.settings, request, open_output))
            return SimpleNamespace(path=self.settings.output_path / "image.png")

    monkeypatch.chdir(outside)
    monkeypatch.setattr(
        generator_module,
        "build_generator",
        lambda settings, *, content_client: (
            FakeGenerator(settings)
            if content_client is expected_client
            else pytest.fail("CLI replaced its content client")
        ),
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
    settings, request, open_output = generated[0]
    assert settings.output_path == expected_output
    assert request == GenerationRequest(1, 1, 1)
    assert open_output is False


def test_interactive_mode_keeps_prompt_and_repeat_flow(monkeypatch, tmp_path):
    _install_chapter_client(monkeypatch)
    config_path = _write_config(
        tmp_path / "config.yaml",
        **{"translation languages": ""},
    )
    generated: list[GenerationRequest] = []
    answers = iter(("1", "1", "1", "n"))

    class FakeGenerator:
        def generate(self, request, *, open_output):
            generated.append(request)
            assert open_output is True
            return SimpleNamespace(path=tmp_path / "image.png")

    monkeypatch.setattr(
        generator_module,
        "build_generator",
        lambda settings, **kwargs: FakeGenerator(),
    )
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    assert cli.main(["--config", str(config_path)]) == 0
    assert generated == [GenerationRequest(1, 1, 1)]


def test_interactive_repeat_reuses_one_client_and_reloads_config(
    monkeypatch, tmp_path
):
    expected_client = _install_chapter_client(monkeypatch)
    config_path = _write_config(
        tmp_path / "config.yaml",
        **{"translation languages": "", "background color": "#000000"},
    )
    answers = iter(("1", "1", "1", "y", "1", "2", "2", "n"))
    builds = []
    generated = []

    class FakeGenerator:
        def __init__(self, settings):
            self.settings = settings

        def generate(self, request, *, open_output):
            generated.append((request, self.settings.background_color))
            if len(generated) == 1:
                values = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                values["background color"] = "#123456"
                config_path.write_text(yaml.safe_dump(values), encoding="utf-8")
            return SimpleNamespace(path=tmp_path / "image.png")

    def fake_build(settings, *, content_client):
        builds.append((settings, content_client))
        return FakeGenerator(settings)

    monkeypatch.setattr(generator_module, "build_generator", fake_build)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    assert cli.main(["--config", str(config_path)]) == 0
    assert [client for _settings, client in builds] == [
        expected_client,
        expected_client,
    ]
    assert generated == [
        (GenerationRequest(1, 1, 1), "#000000"),
        (GenerationRequest(1, 2, 2), "#123456"),
    ]


def test_interactive_prompt_uses_sparse_live_chapter_bounds(monkeypatch, capsys):
    answers = iter(("1", "2", "287", "286", "285", "286"))
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    request = cli._prompt_for_range((Chapter(2, "Al-Baqarah", 286),))

    assert request == GenerationRequest(2, 286, 286)
    output = capsys.readouterr().out
    assert "Available chapter numbers: 2" in output
    assert "between 1 and 286" in output
    assert "between 286 and 286" in output


def test_content_failure_exits_cleanly_before_publish(monkeypatch, tmp_path, capsys):
    from quran_image_generator.content import TranslationTransportError

    config_path = _write_config(
        tmp_path / "config.yaml", **{"translation languages": ""}
    )
    _install_chapter_client(monkeypatch)

    class FailingGenerator:
        def generate(self, request, *, open_output):
            raise TranslationTransportError(
                "loading translation failed after 3 attempts"
            )

    monkeypatch.setattr(
        generator_module,
        "build_generator",
        lambda settings, **kwargs: FailingGenerator(),
    )
    monkeypatch.setattr(
        cli,
        "_publish_generated_image",
        lambda path, target: pytest.fail(f"unexpected publish: {path} {target}"),
    )

    with pytest.raises(SystemExit) as caught:
        cli.main(
            [
                "--config",
                str(config_path),
                "--chapter",
                "1",
                "--start",
                "1",
                "--end",
                "1",
                "--publish",
                "post",
            ]
        )

    assert caught.value.code == 1
    captured = capsys.readouterr()
    assert "Quran data error:" in captured.err
    assert "after 3 attempts" in captured.err
    assert "Traceback" not in captured.err
    assert "Image Created" not in captured.out


def test_translation_selection_failure_is_safe_and_actionable(
    monkeypatch, tmp_path, capsys
):
    from quran_image_generator.content import TranslationSelectionError

    config_path = _write_config(
        tmp_path / "config.yaml",
        **{"translation languages": [{"language": "en"}]},
    )
    _install_chapter_client(monkeypatch)

    class FailingGenerator:
        def generate(self, request, *, open_output):
            raise TranslationSelectionError(
                "Translation language=en is ambiguous; choose key=english_saheeh."
            )

    monkeypatch.setattr(
        generator_module,
        "build_generator",
        lambda settings, **kwargs: FailingGenerator(),
    )

    with pytest.raises(SystemExit) as caught:
        cli.main(
            [
                "--config",
                str(config_path),
                "--chapter",
                "1",
                "--start",
                "1",
                "--end",
                "1",
            ]
        )

    assert caught.value.code == 1
    error = capsys.readouterr().err
    assert "language=en is ambiguous" in error
    assert "key=english_saheeh" in error
    assert "Traceback" not in error


@pytest.mark.parametrize("target", ["post", "story"])
def test_explicit_publish_runs_once_after_successful_generation(
    monkeypatch, tmp_path, target
):
    _install_chapter_client(monkeypatch)
    config_path = _write_config(
        tmp_path / "config.yaml", **{"translation languages": ""}
    )
    output_directory = tmp_path / "output"
    events: list[tuple[str, object]] = []

    class FakeGenerator:
        def __init__(self, settings):
            self.settings = settings

        def generate(self, request, *, open_output):
            image_path = self.settings.output_path / "generated.png"
            image_path.write_bytes(b"retained")
            events.append(("generate", request))
            return SimpleNamespace(path=image_path)

    def fake_publish(path, selected_target):
        assert path.read_bytes() == b"retained"
        events.append(("publish", (path, selected_target)))

    monkeypatch.setattr(
        generator_module,
        "build_generator",
        lambda settings, **kwargs: FakeGenerator(settings),
    )
    monkeypatch.setattr(cli, "_publish_generated_image", fake_publish)

    result = cli.main(
        [
            "--config",
            str(config_path),
            "--output-dir",
            str(output_directory),
            "--chapter",
            "1",
            "--start",
            "1",
            "--end",
            "1",
            "--publish",
            target,
        ]
    )

    image_path = output_directory / "generated.png"
    assert result == 0
    assert events == [
        ("generate", GenerationRequest(1, 1, 1)),
        ("publish", (image_path, target)),
    ]


def test_no_publish_option_never_calls_publishing_path(monkeypatch, tmp_path):
    _install_chapter_client(monkeypatch)
    config_path = _write_config(
        tmp_path / "config.yaml", **{"translation languages": ""}
    )

    class FakeGenerator:
        def __init__(self, settings):
            self.settings = settings

        def generate(self, request, *, open_output):
            image_path = self.settings.output_path / "generated.png"
            image_path.write_bytes(b"retained")
            return SimpleNamespace(path=image_path)

    monkeypatch.setattr(
        generator_module,
        "build_generator",
        lambda settings, **kwargs: FakeGenerator(settings),
    )
    monkeypatch.setattr(
        cli,
        "_publish_generated_image",
        lambda path, target: pytest.fail(f"unexpected publish: {path} {target}"),
    )

    assert (
        cli.main(
            [
                "--config",
                str(config_path),
                "--chapter",
                "1",
                "--start",
                "1",
                "--end",
                "1",
            ]
        )
        == 0
    )


@pytest.mark.parametrize("generated_path", [None, "missing.png"])
def test_publish_is_not_attempted_without_a_retained_output(
    monkeypatch, tmp_path, capsys, generated_path
):
    _install_chapter_client(monkeypatch)
    config_path = _write_config(
        tmp_path / "config.yaml", **{"translation languages": ""}
    )

    class FakeGenerator:
        def generate(self, request, *, open_output):
            path = None if generated_path is None else tmp_path / generated_path
            return SimpleNamespace(path=path)

    monkeypatch.setattr(
        generator_module,
        "build_generator",
        lambda settings, **kwargs: FakeGenerator(),
    )
    monkeypatch.setattr(
        cli,
        "_publish_generated_image",
        lambda path, target: pytest.fail("publishing must not be attempted"),
    )

    result = cli.main(
        [
            "--config",
            str(config_path),
            "--chapter",
            "1",
            "--start",
            "1",
            "--end",
            "1",
            "--publish",
            "post",
        ]
    )

    assert result == 3
    assert "publishing was requested" in capsys.readouterr().err.lower()


def test_publish_failure_returns_distinct_code_and_reports_retained_path(
    monkeypatch, tmp_path, capsys
):
    _install_chapter_client(monkeypatch)
    config_path = _write_config(
        tmp_path / "config.yaml", **{"translation languages": ""}
    )
    sentinel = "must-not-leak"

    class FakeGenerator:
        def __init__(self, settings):
            self.settings = settings

        def generate(self, request, *, open_output):
            image_path = self.settings.output_path / "generated.png"
            image_path.write_bytes(b"retained")
            return SimpleNamespace(path=image_path)

    def failing_publish(path, target):
        raise PublishingError("Instagram upload failed safely.") from RuntimeError(
            sentinel
        )

    monkeypatch.setattr(
        generator_module,
        "build_generator",
        lambda settings, **kwargs: FakeGenerator(settings),
    )
    monkeypatch.setattr(cli, "_publish_generated_image", failing_publish)

    result = cli.main(
        [
            "--config",
            str(config_path),
            "--chapter",
            "1",
            "--start",
            "1",
            "--end",
            "1",
            "--publish",
            "story",
        ]
    )

    image_path = tmp_path / "outputs" / "generated.png"
    error_output = capsys.readouterr().err
    assert result == 3
    assert str(image_path) in error_output
    assert "retained" in error_output
    assert sentinel not in error_output
    assert image_path.read_bytes() == b"retained"


def test_generation_failure_never_reaches_publishing(monkeypatch, tmp_path):
    _install_chapter_client(monkeypatch)
    config_path = _write_config(
        tmp_path / "config.yaml", **{"translation languages": ""}
    )

    class FakeGenerator:
        def generate(self, request, *, open_output):
            raise RuntimeError("generation failed")

    monkeypatch.setattr(
        generator_module,
        "build_generator",
        lambda settings, **kwargs: FakeGenerator(),
    )
    monkeypatch.setattr(
        cli,
        "_publish_generated_image",
        lambda path, target: pytest.fail("publishing must not be attempted"),
    )

    with pytest.raises(RuntimeError, match="generation failed"):
        cli.main(
            [
                "--config",
                str(config_path),
                "--chapter",
                "1",
                "--start",
                "1",
                "--end",
                "1",
                "--publish",
                "post",
            ]
        )


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
