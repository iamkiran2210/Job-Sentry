"""Export endpoint request/response schemas from the FastAPI OpenAPI model."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app


def refs_in(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for child in value.values():
            found.update(refs_in(child))
    elif isinstance(value, list):
        for child in value:
            found.update(refs_in(child))
    return found


def json_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n```"


def main() -> None:
    schema = app.openapi()
    lines = [
        "# API endpoint reference",
        "",
        "Generated from `app.openapi()` by `scripts/export_endpoint_markdown.py`.",
        "Request and response schemas reflect the current OpenAPI document. UUIDs, enum values, nullability, and required fields are included in the schemas below.",
        "",
    ]
    used_schemas: set[str] = set()
    operations: list[tuple[str, str, dict[str, Any]]] = []
    for path, path_item in sorted(schema["paths"].items()):
        for method, operation in sorted(path_item.items()):
            if method.lower() not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            operations.append((method.upper(), path, operation))

    for method, path, operation in operations:
        lines.extend(
            [
                f"## `{method} {path}`",
                "",
                f"**Summary:** {operation.get('summary') or 'Not provided'}  ",
                f"**Operation ID:** `{operation.get('operationId') or 'Not provided'}`  ",
                f"**Tags:** {', '.join(operation.get('tags', [])) or 'None'}",
                "",
                operation.get("description", ""),
                "",
                "### Request",
                "",
            ]
        )
        parameters = operation.get("parameters", [])
        if parameters:
            lines.extend(["Parameters:", ""])
            for parameter in parameters:
                lines.extend(
                    [
                        f"- `{parameter.get('in', 'query')} {parameter['name']}`"
                        f" — {'required' if parameter.get('required') else 'optional'}"
                        f"; schema `{json.dumps(parameter.get('schema', {}), sort_keys=True)}`"
                        + (f"; {parameter['description']}" if parameter.get("description") else "")
                    ]
                )
            lines.append("")
        request_body = operation.get("requestBody")
        if request_body:
            lines.append(
                f"Request body: {'required' if request_body.get('required') else 'optional'}"
            )
            for media_type, media in request_body.get("content", {}).items():
                request_schema = media.get("schema", {})
                used_schemas.update(refs_in(request_schema))
                lines.extend([f"", f"Content-Type: `{media_type}`", "", json_block(request_schema)])
                example = media.get("example")
                if example is not None:
                    lines.extend(["", "Example:", "", json_block(example)])
                examples = media.get("examples", {})
                for name, example_obj in examples.items():
                    if "value" in example_obj:
                        lines.extend(
                            ["", f"Example ({name}):", "", json_block(example_obj["value"])]
                        )
            lines.append("")
        else:
            lines.extend(["No request body.", ""])

        lines.extend(["### Responses", ""])
        for status, response in sorted(operation.get("responses", {}).items()):
            lines.extend([f"#### `{status}` — {response.get('description', 'No description')}", ""])
            content = response.get("content", {})
            if not content:
                lines.extend(["No response body schema is documented.", ""])
                continue
            for media_type, media in content.items():
                response_schema = media.get("schema", {})
                used_schemas.update(refs_in(response_schema))
                lines.extend([f"Content-Type: `{media_type}`", "", json_block(response_schema), ""])
                example = media.get("example")
                if example is not None:
                    lines.extend(["Example:", "", json_block(example), ""])

    components = schema.get("components", {}).get("schemas", {})
    lines.extend(["## Referenced schema components", ""])
    pending = set(used_schemas)
    emitted: set[str] = set()
    while pending:
        name = min(pending)
        pending.remove(name)
        if name in emitted or name not in components:
            continue
        emitted.add(name)
        component = components[name]
        pending.update(refs_in(component) - emitted)
        lines.extend([f"### `{name}`", "", json_block(component), ""])

    output = Path(__file__).resolve().parents[2] / "info" / "API_ENDPOINTS.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {len(operations)} endpoints to {output.relative_to(output.parents[1])}")


if __name__ == "__main__":
    main()
