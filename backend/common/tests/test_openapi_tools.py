"""Agent tools come from the OpenAPI schema and nothing else."""
from __future__ import annotations

import copy

import pytest

from core.openapi_tools import build_request, tool_name, tools_from_openapi


def op(level="allow", **extra):
    return {"summary": "Do it", "description": "Longer text.", "x-permission": "machine.read", "x-agent": level,
            "responses": {"200": {"content": {"application/json": {"schema": {}}}}}, **extra}


SCHEMA = {
    "paths": {
        "/api/v1/modules/machine_state/state": {"get": op()},
        "/api/v1/modules/program/run": {"post": op("confirm", **{"x-permission": "program.run"})},
        "/api/v1/system/update": {"post": op("deny")},
        "/api/v1/old": {"get": op(deprecated=True)},
        "/ws/_schema": {"get": op(**{"x-mcp": False})},
        "/api/v1/upload": {"post": op(requestBody={"content": {"multipart/form-data": {"schema": {}}}})},
        "/api/v1/stream": {"get": op(responses={"200": {"content": {"multipart/x-mixed-replace": {}}}})},
        "/api/v1/files/{filename}": {
            "get": op(parameters=[{"in": "path", "name": "filename", "required": True, "schema": {"type": "string"}},
                                  {"in": "query", "name": "lines", "schema": {"type": "integer"}, "description": "How many"}]),
        },
        "/api/v1/raw/{filename:path}": {"get": op(parameters=[{"in": "path", "name": "filename", "schema": {"type": "string"}}])},
        "/api/v1/hal/pins/values": {
            "post": op(requestBody={"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pins"}}}}),
        },
        "/api/v1/macros/{name}": {"put": op(requestBody={"content": {"text/plain": {"schema": {"type": "string"}}}},
                                            parameters=[{"in": "path", "name": "name", "schema": {"type": "string"}}])},
    },
    "components": {"schemas": {
        "Pins": {"type": "object", "properties": {"pins": {"type": "array", "items": {"$ref": "#/components/schemas/Pin"}}}},
        "Pin": {"type": "string"},
    }},
}


def names(tools):
    return {t.name for t in tools}


def test_only_what_the_schema_allows():
    got = names(tools_from_openapi("machine", SCHEMA))
    assert got == {
        "machine_get_machine_state_state", "machine_get_files_filename", "machine_get_raw_filename",
        "machine_post_hal_pins_values", "machine_put_macros_name",
    }
    with_confirm = names(tools_from_openapi("machine", SCHEMA, offer_confirm=True))
    assert with_confirm - got == {"machine_post_program_run"}


def test_the_schema_is_the_switch():
    """Change the schema, the tools change: there is no second list."""
    schema = copy.deepcopy(SCHEMA)
    schema["paths"]["/api/v1/modules/machine_state/state"]["get"]["x-agent"] = "deny"
    assert "machine_get_machine_state_state" not in names(tools_from_openapi("machine", schema))
    schema["paths"]["/api/v1/system/update"]["post"]["x-agent"] = "allow"
    assert "machine_post_system_update" in names(tools_from_openapi("machine", schema))


def test_arguments_and_description_come_from_the_operation():
    tool = next(t for t in tools_from_openapi("machine", SCHEMA) if t.name == "machine_get_files_filename")
    assert tool.input_schema["properties"]["lines"] == {"type": "integer", "description": "How many"}
    assert tool.input_schema["required"] == ["filename"]
    assert tool.description.startswith("Do it\n\nLonger text.")
    assert "(permission: machine.read; agent: allow)" in tool.description
    assert tool.read_only


def test_body_schemas_are_inlined_as_defs():
    tool = next(t for t in tools_from_openapi("machine", SCHEMA) if t.name == "machine_post_hal_pins_values")
    schema = tool.input_schema
    assert schema["properties"]["body"]["$ref"] == "#/$defs/Pins"
    assert set(schema["$defs"]) == {"Pins", "Pin"}
    assert schema["$defs"]["Pins"]["properties"]["pins"]["items"]["$ref"] == "#/$defs/Pin"
    assert schema["required"] == ["body"]


def test_tool_names():
    assert tool_name("machine", "POST", "/api/v1/modules/program/run") == "machine_post_program_run"
    assert tool_name("system", "GET", "/api/settings") == "system_get_api_settings"  # not /api/v1/settings
    assert tool_name("system", "GET", "/") == "system_get_root"
    assert len(tool_name("system", "GET", "/api/v1/" + "x/" * 60)) <= 64


def test_requests():
    tools = {t.name: t for t in tools_from_openapi("machine", SCHEMA)}
    r = build_request(tools["machine_get_files_filename"], {"filename": "a b.ngc", "lines": 5, "junk": 1})
    assert (r.method, r.path, r.params) == ("GET", "/api/v1/files/a%20b.ngc", {"lines": 5})
    r = build_request(tools["machine_get_raw_filename"], {"filename": "dir/part.ngc"})
    assert r.path == "/api/v1/raw/dir/part.ngc"  # {x:path} keeps its slashes
    r = build_request(tools["machine_get_files_filename"], {"filename": "dir/part.ngc"})
    assert r.path == "/api/v1/files/dir%2Fpart.ngc"
    r = build_request(tools["machine_post_hal_pins_values"], {"body": {"pins": ["a"]}})
    assert r.json == {"pins": ["a"]} and r.text is None
    r = build_request(tools["machine_put_macros_name"], {"name": "m", "body": "G28"})
    assert r.text == "G28" and r.json is None
    with pytest.raises(ValueError, match="filename"):
        build_request(tools["machine_get_files_filename"], {})


def test_the_agent_token_is_created_once_and_private(tmp_path, monkeypatch):
    import os
    import stat

    from core import agent_token as module

    monkeypatch.delenv(module.ENV, raising=False)
    monkeypatch.setattr(module, "TOKEN_FILE", tmp_path / "data" / "agent.token")
    module.agent_token.cache_clear()
    try:
        first = module.agent_token()
        assert len(first) >= 32
        assert stat.S_IMODE(os.stat(module.TOKEN_FILE).st_mode) == 0o600
        module.agent_token.cache_clear()
        assert module.agent_token() == first  # read back, not regenerated
        assert module.is_agent_token(first) and not module.is_agent_token("") and not module.is_agent_token("x")
    finally:
        module.agent_token.cache_clear()
