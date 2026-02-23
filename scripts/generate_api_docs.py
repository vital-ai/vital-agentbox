#!/usr/bin/env python3
"""Generate Markdown API reference docs from FastAPI OpenAPI schemas.

Usage:
    python scripts/generate_api_docs.py

Outputs:
    docs/api/worker-api.md
    docs/api/orchestrator-api.md
"""

from __future__ import annotations

import json
import os
import sys

# Ensure the project root is on sys.path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def schema_to_markdown(schema: dict, title: str, description: str) -> str:
    """Convert an OpenAPI schema dict to a Markdown document."""
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> Auto-generated from OpenAPI schema. Do not edit manually.")
    lines.append(f"> Regenerate with: `python scripts/generate_api_docs.py`")
    lines.append("")
    lines.append(description)
    lines.append("")

    info = schema.get("info", {})
    if info.get("version"):
        lines.append(f"**Version**: {info['version']}")
        lines.append("")

    # Servers
    servers = schema.get("servers", [])
    if servers:
        lines.append("## Servers")
        lines.append("")
        for s in servers:
            lines.append(f"- `{s.get('url', '')}` — {s.get('description', '')}")
        lines.append("")

    # Group endpoints by tag
    paths = schema.get("paths", {})
    tagged: dict[str, list[tuple[str, str, dict]]] = {}
    for path, methods in sorted(paths.items()):
        for method, op in methods.items():
            if method in ("parameters", "servers", "summary", "description"):
                continue
            tags = op.get("tags", ["Other"])
            for tag in tags:
                tagged.setdefault(tag, []).append((method.upper(), path, op))

    for tag in sorted(tagged.keys()):
        lines.append(f"## {tag}")
        lines.append("")

        for method, path, op in tagged[tag]:
            summary = op.get("summary", "")
            op_id = op.get("operationId", "")
            lines.append(f"### `{method} {path}`")
            lines.append("")
            if summary:
                lines.append(summary)
                lines.append("")

            # Parameters
            params = op.get("parameters", [])
            if params:
                lines.append("**Parameters:**")
                lines.append("")
                lines.append("| Name | In | Type | Required | Description |")
                lines.append("|------|----|------|----------|-------------|")
                for p in params:
                    name = p.get("name", "")
                    loc = p.get("in", "")
                    required = "Yes" if p.get("required") else "No"
                    desc = p.get("description", "")
                    p_schema = p.get("schema", {})
                    p_type = _schema_type(p_schema)
                    lines.append(f"| `{name}` | {loc} | `{p_type}` | {required} | {desc} |")
                lines.append("")

            # Request body
            body = op.get("requestBody", {})
            if body:
                content = body.get("content", {})
                for media, media_schema in content.items():
                    ref_schema = media_schema.get("schema", {})
                    lines.append(f"**Request body** (`{media}`):")
                    lines.append("")
                    _render_schema_table(ref_schema, schema, lines)
                    lines.append("")

            # Responses
            responses = op.get("responses", {})
            if responses:
                lines.append("**Responses:**")
                lines.append("")
                for code, resp in sorted(responses.items()):
                    resp_desc = resp.get("description", "")
                    lines.append(f"- **{code}**: {resp_desc}")
                    resp_content = resp.get("content", {})
                    for media, media_schema in resp_content.items():
                        ref_schema = media_schema.get("schema", {})
                        if ref_schema:
                            lines.append("")
                            _render_schema_table(ref_schema, schema, lines)
                lines.append("")

            lines.append("---")
            lines.append("")

    # Schemas section
    components = schema.get("components", {}).get("schemas", {})
    if components:
        lines.append("## Schemas")
        lines.append("")
        for name, s in sorted(components.items()):
            lines.append(f"### {name}")
            lines.append("")
            desc = s.get("description", "")
            if desc:
                lines.append(desc)
                lines.append("")
            _render_schema_table(s, schema, lines)
            lines.append("")

    return "\n".join(lines)


def _schema_type(s: dict) -> str:
    """Extract a human-readable type from a JSON Schema."""
    if "$ref" in s:
        return s["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in s:
        types = [_schema_type(t) for t in s["anyOf"]]
        return " | ".join(types)
    if "allOf" in s:
        types = [_schema_type(t) for t in s["allOf"]]
        return " & ".join(types)
    t = s.get("type", "any")
    if t == "array":
        items = s.get("items", {})
        return f"array[{_schema_type(items)}]"
    if s.get("enum"):
        return " | ".join(f'`"{v}"`' for v in s["enum"])
    fmt = s.get("format", "")
    if fmt:
        return f"{t} ({fmt})"
    return t


def _resolve_ref(ref: str, root_schema: dict) -> dict:
    """Resolve a $ref to the actual schema dict."""
    parts = ref.lstrip("#/").split("/")
    node = root_schema
    for p in parts:
        node = node.get(p, {})
    return node


def _render_schema_table(s: dict, root_schema: dict, lines: list[str]) -> None:
    """Render a schema's properties as a Markdown table."""
    if "$ref" in s:
        s = _resolve_ref(s["$ref"], root_schema)

    props = s.get("properties", {})
    if not props:
        # Maybe it's a simple type
        t = _schema_type(s)
        if t != "any":
            lines.append(f"Type: `{t}`")
        return

    required = set(s.get("required", []))
    lines.append("| Field | Type | Required | Description |")
    lines.append("|-------|------|----------|-------------|")
    for name, prop in props.items():
        p_type = _schema_type(prop)
        req = "Yes" if name in required else "No"
        desc = prop.get("description", prop.get("title", ""))
        default = prop.get("default")
        if default is not None:
            desc += f" (default: `{default}`)"
        lines.append(f"| `{name}` | `{p_type}` | {req} | {desc} |")


def generate_docs():
    """Generate API docs for worker and orchestrator."""
    docs_dir = os.path.join(ROOT, "docs", "api")
    os.makedirs(docs_dir, exist_ok=True)

    # Worker API
    try:
        from agentbox.api.app import app as worker_app
        worker_schema = worker_app.openapi()
        md = schema_to_markdown(
            worker_schema,
            "Worker REST API",
            "REST API for the AgentBox worker process. Handles sandbox lifecycle,\n"
            "code execution, and file operations directly.",
        )
        out = os.path.join(docs_dir, "worker-api.md")
        with open(out, "w") as f:
            f.write(md)
        n = len(worker_schema.get("paths", {}))
        print(f"  Worker API: {n} endpoints -> {out}")
    except Exception as e:
        print(f"  Worker API: FAILED — {e}", file=sys.stderr)

    # Orchestrator API
    try:
        from agentbox.orchestrator.app import app as orch_app
        orch_schema = orch_app.openapi()
        md = schema_to_markdown(
            orch_schema,
            "Orchestrator REST API",
            "REST API for the AgentBox orchestrator. Handles worker registration,\n"
            "request routing, and sandbox lifecycle across multiple workers.",
        )
        out = os.path.join(docs_dir, "orchestrator-api.md")
        with open(out, "w") as f:
            f.write(md)
        n = len(orch_schema.get("paths", {}))
        print(f"  Orchestrator API: {n} endpoints -> {out}")
    except Exception as e:
        print(f"  Orchestrator API: FAILED — {e}", file=sys.stderr)

    # Also dump raw JSON for reference
    json_dir = os.path.join(docs_dir, "openapi")
    os.makedirs(json_dir, exist_ok=True)
    try:
        from agentbox.api.app import app as worker_app
        with open(os.path.join(json_dir, "worker.json"), "w") as f:
            json.dump(worker_app.openapi(), f, indent=2)
    except Exception:
        pass
    try:
        from agentbox.orchestrator.app import app as orch_app
        with open(os.path.join(json_dir, "orchestrator.json"), "w") as f:
            json.dump(orch_app.openapi(), f, indent=2)
    except Exception:
        pass


if __name__ == "__main__":
    print("Generating API docs...")
    generate_docs()
    print("Done.")
