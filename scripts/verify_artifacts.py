"""Verify that a build contains one wheel/sdist and one copy of package data."""

from __future__ import annotations

import argparse
import configparser
import tarfile
import zipfile
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath


def _fail(message: str) -> None:
    raise SystemExit(message)


def _expected_package_files(source: Path) -> tuple[PurePosixPath, ...]:
    expected = []
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if path.is_file() and (path.suffix == ".py" or relative.parts[0] == "assets"):
            expected.append(PurePosixPath(relative.as_posix()))
    if not expected:
        _fail(f"no package files found below {source}")
    return tuple(sorted(expected))


def _duplicates(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(name for name, count in Counter(names).items() if count != 1)


def _verify_wheel(wheel: Path, expected: tuple[PurePosixPath, ...]) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = tuple(item.filename for item in archive.infolist() if not item.is_dir())
        entry_point_names = tuple(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        if len(entry_point_names) != 1:
            _fail("wheel must contain exactly one dist-info/entry_points.txt")
        entry_points = configparser.ConfigParser()
        entry_points.read_string(archive.read(entry_point_names[0]).decode("utf-8"))
    duplicates = _duplicates(names)
    if duplicates:
        _fail(f"wheel has duplicate entries: {', '.join(duplicates)}")
    if any(name.endswith("/assets/verse_bounds.txt") for name in names):
        _fail("wheel contains removed static verse bounds")

    for relative in expected:
        member = f"quran_image_generator/{relative.as_posix()}"
        if names.count(member) != 1:
            _fail(f"wheel must contain exactly one {member}")
    if any(name.startswith(("tests/", "readme_images/")) for name in names):
        _fail("wheel unexpectedly contains tests or README images")
    expected_entries = {
        ("console_scripts", "quran-image-generator"): "quran_image_generator.cli:main",
        (
            "console_scripts",
            "quran-caption-render",
        ): "quran_image_generator.machine_cli:main",
        ("gui_scripts", "quran-image-generator-gui"): (
            "quran_image_generator.gui_cli:main"
        ),
    }
    for (section, name), target in expected_entries.items():
        if entry_points.get(section, name, fallback=None) != target:
            _fail(f"wheel is missing {section} entry point {name} = {target}")


def _verify_sdist(sdist: Path, expected: tuple[PurePosixPath, ...]) -> None:
    with tarfile.open(sdist, mode="r:gz") as archive:
        names = tuple(member.name for member in archive.getmembers() if member.isfile())
    duplicates = _duplicates(names)
    if duplicates:
        _fail(f"sdist has duplicate entries: {', '.join(duplicates)}")
    if any(name.endswith("/assets/verse_bounds.txt") for name in names):
        _fail("sdist contains removed static verse bounds")

    for relative in expected:
        suffix = f"/src/quran_image_generator/{relative.as_posix()}"
        matches = [name for name in names if name.endswith(suffix)]
        if len(matches) != 1:
            _fail(f"sdist must contain exactly one package file ending in {suffix}")


def verify(dist: Path, source: Path) -> tuple[Path, Path]:
    wheels = tuple(dist.glob("*.whl"))
    sdists = tuple(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        _fail(
            "dist must contain exactly one wheel and one sdist; "
            f"found {len(wheels)} wheel(s) and {len(sdists)} sdist(s)"
        )

    expected = _expected_package_files(source)
    _verify_wheel(wheels[0], expected)
    _verify_sdist(sdists[0], expected)
    return wheels[0], sdists[0]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("src/quran_image_generator"),
    )
    args = parser.parse_args(argv)
    wheel, sdist = verify(args.dist, args.source)
    print(f"Artifact inspection passed: {wheel.name}, {sdist.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
