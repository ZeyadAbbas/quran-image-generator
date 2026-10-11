"""Stable field diagnostics shared by the JSON API, Python and native editor."""

from __future__ import annotations

from typing import Any

import jsonschema

from .references import ReferenceError


def pointer(parts: Any) -> str:
    return "".join("/" + str(v).replace("~", "~0").replace("/", "~1") for v in parts)


def schema_diagnostics(value: Any, schema: dict[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    result = []
    for error in jsonschema.Draft202012Validator(schema).iter_errors(value):
        path = prefix + pointer(error.absolute_path)
        if error.validator == "additionalProperties" and isinstance(error.instance, dict):
            known = error.schema.get("properties", {})
            for name in error.instance:
                if name not in known:
                    result.append({"code": "unknown_field", "path": path + pointer([name]),
                                   "value": error.instance[name], "message": "Unsupported field"})
            continue
        result.append({"code": "invalid_field", "path": path, "value": error.instance,
                       "constraint": error.validator, "allowed": error.validator_value,
                       "message": error.message})
    return result[:128]


def validate_schema(value: Any, schema: dict[str, Any], *, code: str = "invalid_request", prefix: str = "") -> None:
    diagnostics = schema_diagnostics(value, schema, prefix)
    if diagnostics:
        raise ReferenceError(code, diagnostics[0]["message"], details={"path": diagnostics[0]["path"], "diagnostics": diagnostics})
