import tempfile
from pathlib import Path

from mcp.types import TextContent

from mcp_code_intelligence.core import formatters


def test_format_definition_single_location_with_excerpt(tmp_path):
    # Create a small Python file
    p = tmp_path / "example.py"
    lines = [f"line {i}\n" for i in range(1, 21)]
    p.write_text("".join(lines), encoding="utf-8")

    resp = {"result": {"uri": p.as_uri(), "range": {"start": {"line": 9, "character": 4}}}}

    contents = formatters.format_definition_response(resp)
    # Should include a header TextContent and at least one code block TextContent
    texts = [c.text for c in contents if hasattr(c, "text")]
    combined = "\n".join(texts)
    assert "File:" in combined
    assert "line" in combined
    assert "```" in combined


def test_format_references_summary(tmp_path):
    # Create a file for URIs
    p = tmp_path / "ref.py"
    p.write_text("print('hello')\n" * 10, encoding="utf-8")

    # Build a large list of mock locations
    payload = []
    for i in range(25):
        payload.append({"uri": p.as_uri(), "range": {"start": {"line": i % 10, "character": 0}}})

    resp = {"result": payload}
    contents = formatters.format_references_response(resp)
    # First content should be summary when >20
    assert any("Toplam" in (c.text if hasattr(c, "text") else "") for c in contents)


def test_format_hover_markdown():
    resp = {"result": {"contents": {"kind": "markdown", "value": "**Hello** world"}}}
    contents = formatters.format_hover_response(resp)
    assert len(contents) == 1
    assert "**Hello**" in contents[0].text


def test_format_completions_list():
    resp = {"result": {"items": [{"label": "foo", "detail": "function foo()"}, {"label": "bar"}]}}
    contents = formatters.format_completions_response(resp, limit=10)
    assert len(contents) == 1
    assert "Completions:" in contents[0].text
    assert "foo" in contents[0].text
