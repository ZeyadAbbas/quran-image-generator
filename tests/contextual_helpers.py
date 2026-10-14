"""Offline reproduction of the consumer's pinned signature preset/fonts."""

import json
from dataclasses import asdict, replace
from pathlib import Path

from test_bindings import fixture_dataset
from test_word_emphasis import FONTS, request

from quran_image_generator.bindings import text_hash
from quran_image_generator.excerpts import ExcerptRequest, select_excerpt


def signature_request(tmp_path, span, *, ornaments=True, spacing=0):
    pinned = json.loads(
        (Path(__file__).parent / "fixtures/word-emphasis-signature.json").read_text(
            "utf8"
        )
    )
    style = pinned["style"]
    for selector in [*pinned["assets"].values(), *style["font_fallbacks"]]:
        selector["path"] = str(FONTS / selector["path"])
    data = request(tmp_path, spans=[asdict(span)], layout="elements", style=style)
    data["profile"]["styles"]["arabic"]["word_spacing"] = spacing
    data.update(
        assets=pinned["assets"],
        caption_groups=pinned["caption_groups"],
        quotations=ornaments,
        verse_numbers=ornaments,
    )
    return data


def with_static_layers(data, spans, *, script="uthmani"):
    """Authored, reviewed phrase binding plus a title and independent track."""
    dataset = fixture_dataset()
    excerpt = select_excerpt(
        ExcerptRequest("fixture", tuple(spans), arabic_script=script)
    )
    binding = replace(
        dataset.bindings[0],
        spans=tuple(spans),
        arabic_sha256=text_hash(excerpt.text),
        mapping_revision=excerpt.spans[0].mapping_revision,
    )
    dataset = replace(dataset, bindings=(binding,))
    data["translation_dataset"] = dataset.to_dict()
    for cue in data["cues"]:
        cue.update(
            translation_policy="required", translation_binding_id=binding.binding_id
        )
    data["titles"] = True
    data["translation_tracks"] = [
        {
            "track_id": "translation-en",
            "language": "en",
            "dataset": dataset.to_dict(),
            "binding": {"binding_id": binding.binding_id, "revision": binding.revision},
            "style": {"anchor": [0.5, 0.9]},
        }
    ]
    if not data.get("caption_groups"):
        data["caption_groups"] = [
            {
                "group_id": "caption",
                "mode": "flow",
                "layers": ["arabic"],
                "region": [0.05, 0.15, 0.95, 0.8],
                "fit": "shrink",
                "gap": 0.22,
            }
        ]
    data["caption_groups"][0]["layers"].extend(["translation", "translation-en"])
    return dataset


def static_assets(cue):
    return [
        plan["asset_id"]
        for plan in cue["layers"]
        if plan["layer"]["role"] != "arabic" and plan["status"] == "ready"
    ]
