from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

import yaml

import read_config
from settings import DEFAULTS, SettingsValidationError, load_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SettingsTests(unittest.TestCase):
    def write_config(self, directory: Path, values: object) -> Path:
        path = directory / "settings.yaml"
        path.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
        return path

    def test_repository_config_is_compatible(self) -> None:
        settings = load_settings(PROJECT_ROOT / "config.yaml", create_output_dir=False)

        self.assertEqual((1080, 1920), settings.resolution.as_tuple())
        self.assertTrue(settings.show_verse_numbers)
        self.assertEqual(["131"], [item.resource_id for item in settings.translations])

    def test_custom_output_path_is_honored_and_created(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = self.write_config(root, {"output path": "generated/images"})

            settings = load_settings(config_path)

            expected = (root / "generated" / "images").resolve()
            self.assertEqual(expected, settings.output_path)
            self.assertTrue(expected.is_dir())

    def test_output_creation_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = self.write_config(root, {"output path": "not-created"})

            settings = load_settings(config_path, create_output_dir=False)

            self.assertEqual((root / "not-created").resolve(), settings.output_path)
            self.assertFalse(settings.output_path.exists())

    def test_empty_translation_configuration_is_an_empty_tuple(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for empty_value in (None, "", "   ", []):
                with self.subTest(empty_value=empty_value):
                    config_path = self.write_config(
                        root, {"translation languages": empty_value}
                    )
                    settings = load_settings(config_path, create_output_dir=False)
                    self.assertEqual((), settings.translations)

    def test_quoted_and_native_scalars_have_the_same_result(self) -> None:
        native = {
            "resolution": [720, 1280],
            "quran font size": 42,
            "quran letter spacing": -0.25,
            "show verse numbers": True,
            "generate random verses": False,
            "upload": "ask",
        }
        quoted = {
            "resolution": "720 x 1280",
            "quran font size": "42",
            "quran letter spacing": "-0.25",
            "show verse numbers": "true",
            "generate random verses": "false",
            "upload": "ask",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            native_path = root / "native.yaml"
            quoted_path = root / "quoted.yaml"
            native_path.write_text(yaml.safe_dump(native), encoding="utf-8")
            quoted_path.write_text(yaml.safe_dump(quoted), encoding="utf-8")

            native_settings = load_settings(native_path, create_output_dir=False)
            quoted_settings = load_settings(quoted_path, create_output_dir=False)

            compared_fields = (
                "resolution",
                "quran_font_size",
                "quran_letter_spacing",
                "show_verse_numbers",
                "generate_random_verses",
                "upload",
            )
            for field in compared_fields:
                self.assertEqual(
                    getattr(native_settings, field), getattr(quoted_settings, field)
                )

    def test_background_resolution_uses_wand_for_svg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            background_path = root / "background.svg"
            background_path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">'
                '<rect width="320" height="180" fill="black"/></svg>',
                encoding="utf-8",
            )
            config_path = self.write_config(
                root,
                {"background image": "background.svg", "resolution": "bg"},
            )

            settings = load_settings(config_path, create_output_dir=False)

            self.assertEqual((320, 180), settings.resolution.as_tuple())

    def test_legacy_translation_syntax_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = self.write_config(
                root,
                {
                    "translation font size": 19,
                    "translation languages": "en:20, fr:Arial:17",
                },
            )

            settings = load_settings(config_path, create_output_dir=False)

            self.assertEqual(
                [("en", "131", 20), ("fr", "31", 17)],
                [
                    (item.language_code, item.resource_id, item.font_size)
                    for item in settings.translations
                ],
            )

    def test_invalid_values_are_reported_together_by_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_path = root / "must-not-be-created"
            config_path = self.write_config(
                root,
                {
                    "output path": str(output_path),
                    "background color": "not-a-color",
                    "quran font size": 0,
                    "show verse numbers": "sometimes",
                    "verse number x offset": 501,
                    "space between verses": -11,
                    "translation languages": "xx",
                    "upload": "later",
                },
            )

            with self.assertRaises(SettingsValidationError) as caught:
                load_settings(config_path)

            fields = {issue.field for issue in caught.exception.issues}
            self.assertTrue(
                {
                    "background color",
                    "quran font size",
                    "show verse numbers",
                    "verse number x offset",
                    "space between verses",
                    "translation languages[0]",
                    "upload",
                }.issubset(fields)
            )
            self.assertFalse(output_path.exists())

    def test_unknown_fields_are_aggregated_with_typo_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = self.write_config(
                root,
                {
                    "quran font sze": 42,
                    "mystery option": True,
                    "quran font size": 0,
                },
            )

            with self.assertRaises(SettingsValidationError) as caught:
                load_settings(config_path, create_output_dir=False)

            issues = {issue.field: issue.message for issue in caught.exception.issues}
            self.assertEqual(
                {"quran font sze", "mystery option", "quran font size"},
                set(issues),
            )
            self.assertIn("did you mean 'quran font size'?", issues["quran font sze"])

    def test_unquoted_numeric_color_is_rejected_instead_of_reformatted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "numeric-color.yaml"
            config_path.write_text("background color: 001234\n", encoding="utf-8")

            with self.assertRaises(SettingsValidationError) as caught:
                load_settings(config_path, create_output_dir=False)

            issue = caught.exception.issues[0]
            self.assertEqual("background color", issue.field)
            self.assertIn("quote hexadecimal colors", issue.message)
            self.assertIn("'001234'", issue.message)

    def test_missing_and_blank_fields_use_deterministic_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = self.write_config(
                root, {"quran font size": "", "show verse numbers": None}
            )

            settings = load_settings(config_path, create_output_dir=False)

            self.assertEqual(DEFAULTS["quran font size"], settings.quran_font_size)
            self.assertEqual(DEFAULTS["show verse numbers"], settings.show_verse_numbers)
            self.assertEqual((root / "outputs").resolve(), settings.output_path)

    def test_malformed_yaml_has_a_focused_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "broken.yaml"
            config_path.write_text("resolution: [1080,\n", encoding="utf-8")

            with self.assertRaises(SettingsValidationError) as caught:
                load_settings(config_path, create_output_dir=False)

            self.assertEqual(["config"], [issue.field for issue in caught.exception.issues])
            self.assertIn("malformed YAML", str(caught.exception))

    def test_existing_file_cannot_be_used_as_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / "an-image.png"
            destination.write_bytes(b"not really an image")
            config_path = self.write_config(root, {"output path": str(destination)})

            with self.assertRaises(SettingsValidationError) as caught:
                load_settings(config_path)

            self.assertEqual("output path", caught.exception.issues[0].field)
            self.assertIn("not a directory", caught.exception.issues[0].message)

    def test_settings_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = self.write_config(Path(temporary_directory), {})
            settings = load_settings(config_path, create_output_dir=False)

            with self.assertRaises(FrozenInstanceError):
                settings.quran_font_size = 99  # type: ignore[misc]

    def test_importing_compatibility_module_has_no_filesystem_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(PROJECT_ROOT)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; import read_config; assert 'wand.image' not in sys.modules",
                ],
                cwd=temporary_directory,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual("", completed.stderr)
            self.assertEqual(0, completed.returncode)
            self.assertFalse((Path(temporary_directory) / "outputs").exists())

    def test_legacy_getters_use_explicitly_loaded_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_path = self.write_config(
                root,
                {
                    "background color": "#abcdef",
                    "show verse numbers": True,
                    "translation languages": "",
                },
            )

            settings = read_config.load_config(config_path, create_output_dir=False)

            self.assertIs(settings, read_config.get_settings())
            self.assertEqual("xc:#ABCDEF", read_config.background_color())
            self.assertTrue(read_config.verse_numbers_visible())
            self.assertEqual({}, read_config.translation_languages())


if __name__ == "__main__":
    unittest.main()
