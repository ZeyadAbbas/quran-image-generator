"""Index canonical Quran word positions and verbatim display-text boundaries.

Orthography is not an approval gate. Equal-sized canonical word runs are indexed
by position; joined words retain their complete source range.
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
REVISION = "simple-uthmani-5"


def positional_groups(group: list, text: str) -> list:
    """Index a known Quran range without revalidating the words' spelling."""
    first, last, start, end = group[:4]
    tokens = [
        m for m in re.finditer(r"\S+", text[start:end]) if skeleton(m.group())
    ]
    if first > last or not tokens:
        raise ValueError("Canonical word ranges must contain source and display words")
    if last - first + 1 != len(tokens):
        return [[first, last, start, end, True]]
    return [
        [
            first + i,
            first + i,
            start + token.start(),
            start + tokens[i + 1].start() if i + 1 < len(tokens) else end,
            True,
        ]
        for i, token in enumerate(tokens)
    ]


def reviewed_groups(approval: dict, group: list, words: list[str], text: str) -> list:
    """Accept only authored, contiguous partitions of an exact generated group."""
    if (
        " ".join(words[group[0] - 1 : group[1]]) != approval["source_text"]
        or text[group[2] : group[3]].rstrip() != approval["target_text"]
        or ("target_range" in approval and approval["target_range"] != group[2:4])
    ):
        raise ValueError("Reviewed boundary spellings no longer match pinned corpora")
    partitions = approval.get("partitions")
    if not partitions:
        return [[*group[:4], True]]
    result = []
    source_start, target_start = group[0], group[2]
    for part in partitions:
        start, end = part["source_words"]
        a, b = part["target_range"]
        if (
            start != source_start
            or a != target_start
            or not start <= end <= group[1]
            or not a < b <= group[3]
            or (a > group[2] and not text[a - 1].isspace())
            or (b < group[3] and not text[b - 1].isspace())
            or " ".join(words[start - 1 : end]) != part["source_text"]
            or text[a:b].rstrip() != part["target_text"]
        ):
            raise ValueError("Reviewed partitions must exactly cover corpus boundaries")
        result.append([start, end, a, b, True])
        source_start, target_start = end + 1, b
    if source_start != group[1] + 1 or target_start != group[3]:
        raise ValueError("Reviewed partitions must cover the entire generated group")
    return result


def skeleton(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(
        str.maketrans(
            {
                "ٱ": "ا",
                "أ": "ا",
                "إ": "ا",
                "آ": "ا",
                "ى": "ي",
                "ٰ": "ا",
                "ۥ": "و",
                "ۦ": "ي",
            }
        )
    )
    return "".join(
        c for c in text if unicodedata.category(c).startswith("L") and c != "ـ"
    )


def records(raw: bytes) -> dict[str, str]:
    return {
        ":".join(line.split("|", 2)[:2]): line.split("|", 2)[2]
        for line in raw.decode("utf-8-sig").splitlines()
        if line and line[0].isdigit()
    }


def build(source: Path, target: Path, output: Path) -> None:
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_HASH:
        raise ValueError("unsupported Simple corpus")
    source_verses, target_verses = records(raw), records(target.read_bytes())
    source_basmala, target_basmala = source_verses["1:1"], target_verses["1:1"]
    source_verses["0:0"], target_verses["0:0"] = source_basmala, target_basmala
    result, review, verse_words = {}, [], {}
    for key, text in source_verses.items():
        target_text = target_verses[key]
        surah, ayah = map(int, key.split(":"))
        offset = 0
        if ayah == 1 and surah not in (1, 9):
            source_tokens = list(re.finditer(r"\S+", text))
            target_tokens = list(re.finditer(r"\S+", target_text))
            assert [skeleton(m.group()) for m in source_tokens[:4]] == [
                skeleton(w) for w in source_basmala.split()
            ]
            assert [skeleton(m.group()) for m in target_tokens[:4]] == [
                skeleton(w) for w in target_basmala.split()
            ]
            text = text[source_tokens[4].start() :]
            offset = target_tokens[4].start()
        words = [m.group() for m in re.finditer(r"\S+", text) if skeleton(m.group())]
        verse_words[key] = words
        tokens = [
            m for m in re.finditer(r"\S+", target_text[offset:]) if skeleton(m.group())
        ]
        groups = []
        # Exact sequence anchors, with non-equal regions retained for review.
        for tag, i, j, a, b in SequenceMatcher(
            None,
            [skeleton(w) for w in words],
            [skeleton(m.group()) for m in tokens],
            autojunk=False,
        ).get_opcodes():
            if tag == "equal":
                for si, ti in zip(range(i, j), range(a, b), strict=True):
                    groups.append(
                        [
                            si + 1,
                            si + 1,
                            tokens[ti].start() + offset,
                            tokens[ti + 1].start() + offset
                            if ti + 1 < len(tokens)
                            else len(target_text),
                            True,
                        ]
                    )
            else:
                approved = (
                    j > i
                    and b > a
                    and "".join(skeleton(w) for w in words[i:j])
                    == "".join(skeleton(m.group()) for m in tokens[a:b])
                )
                start = (
                    tokens[a].start() + offset if a < len(tokens) else len(target_text)
                )
                end = (
                    tokens[b].start() + offset if b < len(tokens) else len(target_text)
                )
                groups.append([i + 1, j, start, end, approved])
                if not approved:
                    review.append(
                        {
                            "verse": key,
                            "source_words": [i + 1, j],
                            "target_range": [start, end],
                            "reason": "orthography_review_required",
                        }
                    )
        result[key] = {"word_count": len(words), "offset": offset, "groups": groups}
    # Explicit authored token equivalences, never approximate matching. Verify
    # both spellings and the original generated offsets before accepting one.
    approvals = json.loads(
        (Path(__file__).parent / "data" / "reviewed-word-boundaries.json").read_text(
            "utf-8"
        )
    )
    for approval in approvals:
        key = approval["verse"]
        group = next(
            g for g in result[key]["groups"] if g[:2] == approval["source_words"]
        )
        replacements = reviewed_groups(
            approval, group, verse_words[key], target_verses[key]
        )
        index = result[key]["groups"].index(group)
        result[key]["groups"][index : index + 1] = replacements
        review = [
            item
            for item in review
            if not (item["verse"] == key and item["source_words"] == group[:2])
        ]
    # The corpora already establish which Quran words these ranges contain.
    # Different written forms cannot make their canonical positions unavailable.
    for key, record in result.items():
        record["groups"] = [
            indexed
            for group in record["groups"]
            for indexed in positional_groups(group, target_verses[key])
        ]
    document = {
        "revision": REVISION,
        "source_sha256": SOURCE_HASH,
        "target_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "verses": result,
        "review": [],
        "authored_equivalences": approvals,
    }
    output.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")), "utf-8"
    )
    print(f"{len(result)} records; canonical word positions indexed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.source, args.target, args.output)
