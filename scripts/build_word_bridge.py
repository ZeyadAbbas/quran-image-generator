"""Build conservative, offline edition mappings; never run during rendering.

Only exact normalized token groups become selectable. All unmatched spelling
groups remain in the checked-in review list. No approximate match is approved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

SOURCE_HASH = "f3268cfe7a400add8a8024fe23368d66f58cc8baa51773fe94e323625c66344b"


def skeleton(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(str.maketrans({
        "ٱ": "ا", "أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي",
        "ٰ": "ا", "ۥ": "و", "ۦ": "ي",
    }))
    return "".join(c for c in text if unicodedata.category(c).startswith("L") and c != "ـ")


def records(raw: bytes) -> dict[str, str]:
    return {":".join(line.split("|", 2)[:2]): line.split("|", 2)[2]
            for line in raw.decode("utf-8-sig").splitlines()
            if line and line[0].isdigit()}


def build(source: Path, target: Path, output: Path) -> None:
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_HASH:
        raise ValueError("unsupported Simple corpus")
    source_verses, target_verses = records(raw), records(target.read_bytes())
    source_basmala, target_basmala = source_verses["1:1"], target_verses["1:1"]
    source_verses["0:0"], target_verses["0:0"] = source_basmala, target_basmala
    result, review = {}, []
    for key, text in source_verses.items():
        target_text = target_verses[key]
        surah, ayah = map(int, key.split(":"))
        offset = 0
        if ayah == 1 and surah not in (1, 9):
            source_tokens = list(re.finditer(r"\S+", text))
            target_tokens = list(re.finditer(r"\S+", target_text))
            assert [skeleton(m.group()) for m in source_tokens[:4]] == [skeleton(w) for w in source_basmala.split()]
            assert [skeleton(m.group()) for m in target_tokens[:4]] == [skeleton(w) for w in target_basmala.split()]
            text = text[source_tokens[4].start():]
            offset = target_tokens[4].start()
        words = [m.group() for m in re.finditer(r"\S+", text) if skeleton(m.group())]
        tokens = [m for m in re.finditer(r"\S+", target_text[offset:]) if skeleton(m.group())]
        groups = []
        # Exact sequence anchors, with non-equal regions retained for review.
        for tag, i, j, a, b in SequenceMatcher(
            None, [skeleton(w) for w in words],
            [skeleton(m.group()) for m in tokens], autojunk=False
        ).get_opcodes():
            if tag == "equal":
                for si, ti in zip(range(i, j), range(a, b), strict=True):
                    groups.append([si + 1, si + 1, tokens[ti].start() + offset,
                                   tokens[ti + 1].start() + offset if ti + 1 < len(tokens) else len(target_text), True])
            else:
                approved = (j > i and b > a and
                            "".join(skeleton(w) for w in words[i:j]) ==
                            "".join(skeleton(m.group()) for m in tokens[a:b]))
                start = tokens[a].start() + offset if a < len(tokens) else len(target_text)
                end = tokens[b].start() + offset if b < len(tokens) else len(target_text)
                groups.append([i + 1, j, start, end, approved])
                if not approved:
                    review.append({"verse": key, "source_words": [i + 1, j],
                                   "target_range": [start, end], "reason": "orthography_review_required"})
        result[key] = {"word_count": len(words), "offset": offset, "groups": groups}
    document = {"revision": "simple-uthmani-1", "source_sha256": SOURCE_HASH,
                "target_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "verses": result, "review": review}
    output.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"{len(result)} records; {len(review)} unresolved spelling groups")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.source, args.target, args.output)
