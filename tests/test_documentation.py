from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from quran_image_generator.settings import SETTING_SPECS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIGURATION_DOC = PROJECT_ROOT / "docs" / "configuration.md"


def _documented_defaults() -> dict[str, str]:
    rows: dict[str, str] = {}
    pattern = re.compile(r"^\| `([^`]+)` \| `([^`]*)` \|")
    for line in CONFIGURATION_DOC.read_text(encoding="utf-8").splitlines():
        if match := pattern.match(line):
            rows[match.group(1)] = match.group(2)
    return rows


def _display_default(value: object) -> str:
    if value == "":
        return "blank"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def test_configuration_reference_tracks_setting_schema() -> None:
    documented = _documented_defaults()
    expected = {spec.key: _display_default(spec.default) for spec in SETTING_SPECS}

    assert documented == expected


def test_local_documentation_links_resolve() -> None:
    markdown_files = [
        PROJECT_ROOT / "README.md",
        *sorted((PROJECT_ROOT / "docs").glob("*.md")),
    ]
    markdown_link = re.compile(r"!?\[[^\]\r\n]*\]\(([^)]+)\)")
    html_link = re.compile(
        r"<(?:img|a)\b[^>\r\n]*(?:src|href)=\"([^\"]+)\"",
        re.IGNORECASE,
    )
    missing: list[str] = []

    for document in markdown_files:
        content = document.read_text(encoding="utf-8")
        targets = [*markdown_link.findall(content), *html_link.findall(content)]
        for target in targets:
            path_text = unquote(target.split("#", 1)[0])
            if not path_text or re.match(r"^[a-z][a-z0-9+.-]*:", path_text, re.I):
                continue
            candidate = (document.parent / path_text).resolve()
            if not candidate.exists():
                missing.append(f"{document.relative_to(PROJECT_ROOT)} -> {target}")

    assert missing == []
