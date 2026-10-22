"""The free MCP tool describes the rails and does not rank a deadline."""

import asyncio
import json

from settlequote.mcp_server import FREE_TOOL, create_mcp, describe


def test_describe_names_the_rails_and_the_price():
    body = describe()
    assert body["price_usd"] == "0.005"
    assert "fedwire" in body["rails"]
    assert "recommendation" not in body
    assert "6:45" not in json.dumps(body)


def test_free_server_has_no_paid_tool():
    mcp = create_mcp(pay_to=None)
    tools = asyncio.run(mcp.list_tools())
    assert [tool.name for tool in tools] == [FREE_TOOL]
    content, _structured = asyncio.run(mcp.call_tool(FREE_TOOL, {}))
    text = content[0].text
    assert "fedwire" in text
    assert "recommendation" not in text
